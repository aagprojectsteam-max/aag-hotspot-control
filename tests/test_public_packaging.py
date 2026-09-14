"""Public binding/distribution regressions; no real network or privileged writes."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'));sys.path.insert(0,str(ROOT/'scripts'))
from aag_hotspot import binding, ownership
from aag_hotspot.backend import Backend
import host_environment as environment
import package
from privacy_scan import findings

CELL='f0000011-0000-4000-8000-000000000011'
SAVED='f0000012-0000-4000-8000-000000000012'
RADIO='Supported interface modes:\n * managed\n * AP\n * 2437 MHz [6] (20.0 dBm)\nvalid interface combinations:\n * #{ managed, AP } <= 2\n'


class BindingTests(unittest.TestCase):
    def test_unbound_source_cannot_activate(self):
        with patch.object(binding,'READY',False),patch.object(Backend,'wifi_idle') as probe:
            with self.assertRaisesRegex(ownership.OperationError,'HOST_BINDING_REQUIRED'):Backend().preflight('internet')
            probe.assert_not_called()

    def test_missing_binding_is_unbound(self):
        with tempfile.TemporaryDirectory() as d:
            data,ready=binding.load(Path(d)/'host.json')
            self.assertFalse(ready);self.assertEqual(data,binding.UNBOUND)

    def test_user_writable_binding_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'host.json';p.write_text(json.dumps(binding.UNBOUND));p.chmod(0o666)
            self.assertFalse(binding.load(p)[1])

    def test_schema_rejects_commands_secrets_and_bad_ids(self):
        for key,value in [('wifi_interface','wlan0; reboot'),('phy',True),('cellular_uuid','invalid'),('protected_uuids',[CELL,CELL]),('password','not-a-config-field')]:
            data=copy.deepcopy(binding.UNBOUND);data[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):binding.validate(data)

    def test_local_only_binding_accepts_no_cellular(self):
        data=copy.deepcopy(binding.UNBOUND);data['cellular_uuid']=None;data['protected_uuids']=[]
        self.assertIs(binding.validate(data),data)

    def test_cellular_must_be_protected(self):
        data=copy.deepcopy(binding.UNBOUND);data['protected_uuids']=[]
        with self.assertRaises(ValueError):binding.validate(data)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.commands=[];self.no_cell=False;self.radio=RADIO;self.devices='phy#2\n Interface wlan1\n  type managed';self.forward='1';self.nmconfig='firewall-backend=iptables';self.version='nmcli tool, version 1.54.0'
        def run(args):
            self.commands.append(args)
            if args[0]=='/usr/bin/python3':return ''
            if args[-3:]==['RUNNING','general','status']:return 'running'
            if args[-1]=='--version':return self.version
            if args[-1]=='--print-config':return self.nmconfig
            if args[-1]=='net.ipv4.ip_forward':return self.forward
            if args==['/usr/sbin/iw','dev']:return self.devices
            if args[:2]==['/usr/sbin/iw','phy']:return self.radio
            if args[-1]=='--active':return '' if self.no_cell else CELL+':gsm:wwan0mbim0'
            if 'UUID,TYPE,NAME' in args:return SAVED+':802-11-wireless:Hotspot\n'+CELL+':gsm:Example cellular'
            raise AssertionError(args)
        for item in (patch.object(environment,'run',side_effect=run),patch.object(environment.platform,'freedesktop_os_release',return_value={'ID':'ubuntu','VERSION_ID':'26.04'}),patch.object(environment.platform,'machine',return_value='x86_64'),patch.object(environment.shutil,'which',return_value='/fixture/bin')):
            item.start();self.addCleanup(item.stop)

    def test_bind_existing_local_identifiers_without_mutation(self):
        value=environment.detect()
        self.assertEqual(value,{'schema':1,'wifi_interface':'wlan1','phy':2,'cellular_uuid':CELL,'protected_uuids':[CELL,SAVED]})
        self.assertFalse(any(word in args for args in self.commands for word in ('up','down','modify','add','delete','set','restart')))

    def test_no_cellular_connection_keeps_local_option(self):
        self.no_cell=True;value=environment.detect();self.assertIsNone(value['cellular_uuid']);self.assertEqual(value['protected_uuids'],[SAVED])

    def test_ambiguous_wifi_requires_explicit_existing_selection(self):
        self.devices+='\nphy#3\n Interface wlan2\n  type managed'
        with self.assertRaisesRegex(RuntimeError,'Select one'):environment.detect()
        self.assertEqual(environment.detect('wlan2')['phy'],3)

    def test_unsupported_os_refuses_before_probes(self):
        with patch.object(environment.platform,'freedesktop_os_release',return_value={'ID':'other','VERSION_ID':'1'}):
            with self.assertRaisesRegex(RuntimeError,'Ubuntu'):environment.detect()
        self.assertEqual(self.commands,[])

    def test_missing_dependency_refuses(self):
        with patch.object(environment.shutil,'which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'Missing dependencies'):environment.detect()

    def test_wrong_firewall_or_forwarding_preserves_global_state(self):
        self.forward='0'
        with self.assertRaisesRegex(RuntimeError,'forwarding'):environment.detect()
        self.forward='1';self.nmconfig='firewall-backend=nftables'
        with self.assertRaisesRegex(RuntimeError,'firewall-backend'):environment.detect()

    def test_unsupported_nm_version(self):
        self.version='nmcli tool, version 1.60.0'
        with self.assertRaisesRegex(RuntimeError,'1.54'):environment.detect()

    def test_ap_or_legal_channel_required(self):
        for value in (RADIO.replace(' * AP\n',''),RADIO.replace('(20.0 dBm)','(disabled)')):
            self.radio=value
            with self.assertRaises(RuntimeError):environment.detect()


class PublicPackageTests(unittest.TestCase):
    def test_public_payload_excludes_reports_and_local_binding(self):
        files=package.source_map()
        self.assertNotIn(package.BINDING,files)
        self.assertFalse(any('reports' in path.parts for path in files))
        self.assertIn(Path('usr/share/doc/aag-hotspot/LICENSE'),files)
        self.assertIn(Path('usr/lib/aag-hotspot/aag_hotspot/binding.py'),files)

    def test_unowned_host_binding_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/package.BINDING;target.parent.mkdir(parents=True);target.write_text('unowned')
            with self.assertRaisesRegex(RuntimeError,'Unowned host binding'):package.install(root,False)
            self.assertEqual(target.read_text(),'unowned')

    def test_staging_never_discovers_or_stops_real_network(self):
        with tempfile.TemporaryDirectory() as d,patch.object(environment,'detect',side_effect=AssertionError('No live probe')),patch.object(package,'stop_for_uninstall',side_effect=AssertionError('No real OFF')),patch.object(package,'refresh'):
            root=Path(d);package.install(root,False);package.uninstall(root,False)

    def test_privacy_scanner_rejects_realistic_values_and_large_files(self):
        self.assertIn('non_fixture_mac',findings(('04'+':12'*5).encode(),'example.py'))
        self.assertIn('non_fixture_uuid',findings(('12345678-'+'1234-'*3+'123456789012').encode(),'example.py'))
        self.assertIn('private_file',findings(b'{}','host.json'))
        self.assertIn('large_file',findings(b'\0'*(2*1024*1024+1),'dump.bin'))
        self.assertFalse(findings(b'02:00:00:00:00:01','fixture.py'))

    def test_modified_installed_helper_never_runs_during_uninstall(self):
        receipt={'files':{'usr/libexec/aag-hotspot-helper':{'sha256':'expected','mode':0o755}}}
        with patch.object(package,'installed_receipt',return_value=receipt),patch.object(package,'checked_path',return_value=Path('/fixture/helper')),patch.object(package,'digest',return_value='changed'),patch.object(package.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'Modified installed'):package.stop_for_uninstall()
            run.assert_not_called()

    def test_protected_system_check_requires_admin_before_probe(self):
        import contextlib,io
        with patch.object(package.sys,'argv',['package','install','--system','--check']),patch.object(package.os,'geteuid',return_value=1000),patch.object(environment,'detect') as probe,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:package.main()
            self.assertEqual(caught.exception.code,2);probe.assert_not_called()

    def test_admin_system_check_is_read_only(self):
        import contextlib,io
        with patch.object(package.sys,'argv',['package','install','--system','--check']),patch.object(package.os,'geteuid',return_value=0),patch.object(environment,'detect',return_value=binding.UNBOUND),patch('aag_hotspot.state.Store',side_effect=AssertionError('No runtime writes')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(package.main(),0)
            self.assertEqual(json.loads(output.getvalue()),{'compatible':True,'network_changes':False,'secrets_read':False})

    def test_repeated_system_uninstall_never_recreates_runtime(self):
        import contextlib,io
        with patch.object(package.sys,'argv',['package','uninstall','--system']),patch.object(package.os,'geteuid',return_value=0),patch.object(package,'installed_receipt',return_value=None),patch.object(package,'stop_for_uninstall') as stop,patch('aag_hotspot.state.Store',side_effect=AssertionError('No runtime recreation')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(package.main(),0)
            self.assertEqual(json.loads(output.getvalue())['status'],'NOT_INSTALLED')
            stop.assert_not_called()

    def test_off_failure_retains_installed_package(self):
        from types import SimpleNamespace
        with patch.object(package,'installed_receipt',return_value={'files':{}}),patch.object(package.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError,'OFF failed'):package.stop_for_uninstall()
            self.assertEqual(run.call_args.args[0],['/usr/libexec/aag-hotspot-helper','off'])


if __name__=='__main__':unittest.main()
