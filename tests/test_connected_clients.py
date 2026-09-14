"""Authoritative client join and expiry regressions; no network operations."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot import clients as c, cli
from aag_hotspot.tray import model, count_label, Indicator, MENU, ITEM
from gi.repository import GLib

VIF = 'aaghp12345678'
MAC = '02:00:00:00:00:01'
OTHER = '02:00:00:00:00:02'


def station(mac=MAC, interface=VIF):
    return f'Station {mac} (on {interface})\n\tsignal: -29 [-29] dBm\n\tconnected time: 256 seconds\n'


def lease(ip='10.77.0.15', name='fixture-tablet', mac=MAC, expiry=2000):
    return f'{expiry} {mac} {ip} {name} *\n'


def neighbor(ip='10.77.0.16', state='REACHABLE', mac=MAC, interface=VIF):
    return json.dumps([{'dst': ip, 'lladdr': mac, 'dev': interface, 'state': [state]}])


class ClientTests(unittest.TestCase):
    def merge(self, s=None, l=None, n='[]'):
        return c.merge(station() if s is None else s, lease() if l is None else l, n, VIF, 1000)

    def test_zero_clients_even_with_leases_and_neighbors(self):
        self.assertEqual(self.merge(s='', n=neighbor()), [])

    def test_one_client_all_fields(self):
        self.assertEqual(self.merge(), [{'mac': MAC, 'ipv4': '10.77.0.15', 'hostname': 'fixture-tablet',
            'signal_dbm': -29, 'connected_seconds': 256, 'ip_source': 'dhcp_lease'}])

    def test_multiple_clients_mac_identity(self):
        rows = self.merge(s=station()+station(OTHER), l=lease()+lease('10.77.0.20', mac=OTHER))
        self.assertEqual([r['mac'] for r in rows], [MAC, OTHER])

    def test_reconnect_new_ip_replaces_old_address(self):
        first = self.merge()[0]
        second = self.merge(l=lease('10.77.0.40'), n=neighbor(state='STALE'))[0]
        self.assertEqual(first['mac'], second['mac'])
        self.assertEqual(second['ipv4'], '10.77.0.40')

    def test_stale_neighbor_does_not_supply_address(self):
        for state in ('STALE', 'FAILED', 'INCOMPLETE', 'DELAY', 'PROBE', 'PERMANENT'):
            self.assertIsNone(self.merge(l='', n=neighbor(state=state))[0]['ipv4'])

    def test_neighbor_fallback_requires_association_and_correct_interface(self):
        self.assertEqual(self.merge(l='', n=neighbor())[0]['ip_source'], 'neighbor_reachable')
        self.assertIsNone(self.merge(l='', n=neighbor(interface='docker0'))[0]['ipv4'])
        self.assertEqual(self.merge(s='', l='', n=neighbor()), [])

    def test_missing_hostname_never_invented(self):
        for name in ('*', '<script>', 'host\u202eexe', 'שלום'):
            self.assertIsNone(self.merge(l=lease(name=name))[0]['hostname'])

    def test_station_without_lease_still_counted(self):
        row = self.merge(l='')[0]
        self.assertIsNone(row['ipv4']); self.assertIsNone(row['hostname'])
        self.assertEqual(row['connected_seconds'], 256)

    def test_lease_for_disconnected_station_excluded(self):
        self.assertEqual(len(self.merge(l=lease()+lease('10.77.0.20', mac=OTHER))), 1)

    def test_expired_lease_clears_ip_and_hostname(self):
        row = self.merge(l=lease(expiry=999))[0]
        self.assertIsNone(row['ipv4']); self.assertIsNone(row['hostname'])

    def test_current_lease_wins_over_neighbor_old_ip(self):
        self.assertEqual(self.merge(n=neighbor())[0]['ipv4'], '10.77.0.15')

    def test_duplicate_lease_ip_and_out_of_subnet_rejected(self):
        self.assertIsNone(self.merge(l=lease()+lease(mac=OTHER))[0]['ipv4'])
        for ip in ('192.168.1.5', '10.77.0.1', '10.77.0.0', '10.77.0.255', '::1'):
            self.assertIsNone(self.merge(l=lease(ip))[0]['ipv4'])

    def test_associated_no_and_foreign_interface(self):
        self.assertEqual(self.merge(s=station()+'\tassociated: no\n'), [])
        with self.assertRaises(ValueError): self.merge(s=station(interface='wlan0'))

    def test_missing_signal_and_time_are_unknown(self):
        row=self.merge(s=f'Station {MAC} (on {VIF})')[0]
        self.assertIsNone(row['signal_dbm']); self.assertIsNone(row['connected_seconds'])

    def test_modes_and_stalled_publication_clear_old_records(self):
        for old, new in (('internet', 'local'), ('local', 'internet')):
            value = {'mode':old,'phase':'active','health':'OK','clients':1,'client_details':self.merge(),
                     'clients_updated_monotonic':50,'client_data_status':'OK'}
            self.assertEqual(len(c.expire(dict(value), 55)['client_details']),1)
            for change in ({'mode':new,'phase':'switching'}, {'phase':'off'}, {'health':'UNKNOWN'}, {'clients_updated_monotonic':0}):
                self.assertEqual(c.expire(value|change,55)['client_details'],[])
            value.update(mode=new,client_details=self.merge(l=lease('10.77.0.30')),clients_updated_monotonic=55)
            self.assertEqual(c.expire(value,55)['client_details'][0]['ipv4'],'10.77.0.30')

    def test_backend_reads_only_owned_interface_and_lease(self):
        owner=SimpleNamespace(vif=VIF,ifindex=70,mac=OTHER,profile_uuid='fixture-profile')
        b=Mock();b.interface.return_value={'mode':'AP','ifindex':70,'mac':OTHER}
        b.active.return_value={owner.profile_uuid:[VIF]}
        b.run.side_effect=[station(),neighbor()]
        with patch.object(c,'read_leases',return_value=lease()) as read, patch.object(c.time,'time',return_value=1000):
            result=c.snapshot(b,owner)
        self.assertEqual(result['clients'],1); read.assert_called_once_with(VIF)
        self.assertEqual(b.run.call_args_list[0].args[0], ['/usr/sbin/iw','dev',VIF,'station','dump'])
        self.assertEqual(b.run.call_args_list[1].args[0], ['/usr/sbin/ip','-j','-4','neigh','show','dev',VIF])

    def test_reused_interface_or_inactive_profile_never_probed(self):
        for device, active in (({'mode':'AP','ifindex':99,'mac':OTHER},{'fixture':[VIF]}),
                               ({'mode':'AP','ifindex':70,'mac':OTHER},{})):
            b=Mock();b.interface.return_value=device;b.active.return_value=active
            owner=SimpleNamespace(vif=VIF,ifindex=70,mac=OTHER,profile_uuid='fixture')
            self.assertEqual(c.snapshot(b,owner)['client_data_status'],'UNAVAILABLE'); b.run.assert_not_called()

    def test_failed_station_probe_returns_unknown_without_private_error(self):
        b=Mock();b.interface.side_effect=RuntimeError('private fixture')
        result=c.snapshot(b,SimpleNamespace(vif=VIF))
        self.assertIsNone(result['clients']);self.assertNotIn('private fixture',str(result))

    def test_lease_file_rejects_symlink_or_external_write_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lease';path.write_text(lease());path.chmod(0o644)
            parent=MagicMock();parent.lstat.return_value=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
            parent.__truediv__.return_value=path
            with patch.object(c,'Path',return_value=parent):
                self.assertEqual(c.read_leases(VIF),lease())
                path.chmod(0o666)
                with self.assertRaises(ValueError):c.read_leases(VIF)
                path.chmod(0o644);link=Path(directory)/'link';link.symlink_to(path)
                parent.__truediv__.return_value=link
                with self.assertRaises(OSError):c.read_leases(VIF)

    def test_probes_have_total_deadline_and_short_command_timeout(self):
        with patch.object(c.time,'monotonic',side_effect=[10,11,17]), patch.object(c.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            probe=c.Probe();probe.run(['/usr/sbin/iw','dev',VIF,'station','dump'])
            self.assertEqual(run.call_args.kwargs['timeout'],2)
            with self.assertRaises(ValueError):probe.run(['/usr/sbin/ip'])
        self.assertEqual(run.call_count,1)

    def test_status_retains_clients_key_and_adds_flat_details(self):
        value={'clients':1,'client_count':1,'client_details':self.merge(),'health':'OK'}
        out=io.StringIO()
        with patch.object(cli.client,'status',return_value=value),contextlib.redirect_stdout(out): self.assertEqual(cli.main(['status']),0)
        self.assertIn('CLIENTS=1\n',out.getvalue());self.assertIn('CLIENT_COUNT=1\n',out.getvalue())
        self.assertIn('CLIENT_1_MAC='+MAC,out.getvalue());self.assertIn('CLIENT_1_IPV4=10.77.0.15',out.getvalue())


class TrayTests(unittest.TestCase):
    def test_modes_and_client_count_updates(self):
        for mode,label in [('off','כבוי'),('internet','אינטרנט'),('local','מקומי בלבד')]:
            for count in (0,1,2,None):
                value=model({'mode':mode,'clients':count})
                self.assertIn(label,value['title'])
                if mode != 'off':self.assertIn(count_label(count),value['title'])
                self.assertIn(count_label(count),[r[1] for r in value['rows']])
        self.assertEqual(count_label(1),'1 מכשיר מחובר')

    def test_menu_event_dispatches_only_explicit_valid_click(self):
        indicator=Indicator.__new__(Indicator);indicator.value=model({'mode':'off','clients':0});indicator.action=Mock()
        with patch.object(GLib,'idle_add') as idle:
            self.assertFalse(indicator.event(999,'clicked'));indicator.event(2,'hovered');indicator.event(1,'clicked')
            idle.assert_not_called();indicator.event(6,'clicked');self.assertEqual(idle.call_count,1)
            idle.call_args.args[0]();indicator.action.assert_called_once_with('open')

    def test_busy_mode_actions_disabled_and_layout_has_rtl_properties(self):
        indicator=Indicator.__new__(Indicator);indicator.value=model({'mode':'local','clients':1},busy=True)
        self.assertFalse(indicator.properties(4)['enabled'].unpack())
        for identifier in (2,3):
            with self.assertRaises(ValueError):indicator.properties(identifier)
        self.assertEqual(indicator.property(None,None,None,MENU,'TextDirection').unpack(),'rtl')
        self.assertEqual(len(indicator.layout(0,-1,[])[2]),6)

    def test_client_count_change_emits_menu_and_indicator_updates(self):
        indicator=Indicator.__new__(Indicator);indicator.value=model({'mode':'local','clients':0});indicator.revision=1
        indicator.bus=Mock();indicator.closed=False
        indicator.update({'mode':'local','clients':1})
        self.assertIn('1 מכשיר מחובר',indicator.value['title'])
        self.assertIn('LayoutUpdated',[call.args[3] for call in indicator.bus.emit_signal.call_args_list])


if __name__=='__main__':unittest.main()
