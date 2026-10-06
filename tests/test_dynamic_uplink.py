"""Route/NM authority, identity independence, isolation and coexistence contracts."""
import copy
from dataclasses import replace
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from aag_hotspot import policy,wifi,binding
from aag_hotspot.uplink import Uplink,detect,require_same,forwarded_path,PROBES
from aag_hotspot.backend import Backend
from aag_hotspot.controller import Controller
from test_production import MemoryStore,MemoryBackend


class Fixture:
    def __init__(self,iface='cell42',kind='gsm',device_type=8,device='modem-control7'):
        self.routes={ip:[{'dev':iface,'prefsrc':'172.30.2.1','gateway':'172.30.2.2','table':201}] for ip in PROBES}
        self.device={'interface':device,'ip_interface':iface,'device_type':device_type,'state':100,
                     'connection_state':2,'connection_type':kind,'name':'Any provider',
                     'uuid':'f0000001-0000-4000-8000-000000000001'}
        self.linkdata={'ifname':iface,'flags':['UP','LOWER_UP']};self.calls=[]
    def route(self,address,**kwargs):
        self.calls.append((address,kwargs))
        if kwargs.get('fibmatch'):return [dict(self.routes[address][0],metric=73)]
        return copy.deepcopy(self.routes[address])
    def nm(self,interface):return dict(self.device)
    def link(self,interface):return copy.deepcopy(self.linkdata)


RADIO='''Supported interface modes:
 * managed
 * AP
 * 2412 MHz [1] (22.0 dBm)
 * 2437 MHz [6] (22.0 dBm)
 * 5180 MHz [36] (22.0 dBm)
 * 5260 MHz [52] (22.0 dBm) (radar detection)
 valid interface combinations:
 * #{ managed } <= 2, #{ AP, P2P-client } <= 1, #{ P2P-device } <= 1,
   total <= 4, #channels <= 1
'''
STA_INFO='Interface wlan0\n\ttype managed\n\twiphy 0\n'
STA_LINK='Connected to 02:00:00:00:00:01 (on wlan0)\n\tfreq: 5180\n'


class DynamicUplinkTests(unittest.TestCase):
    def test_cellular_control_and_ip_device_differ(self):
        selected=detect(Fixture());self.assertTrue(selected.supported)
        self.assertEqual((selected.type,selected.interface,selected.nm_device),('CELLULAR','cell42','modem-control7'))
    def test_recreated_cellular_uuid_is_metadata_not_eligibility(self):
        p=Fixture();before=detect(p)
        p.device['uuid']='f0000003-0000-4000-8000-000000000003';p.device['name']='Different provider'
        after=detect(p);require_same(before,after)
        self.assertTrue(after.supported);self.assertNotEqual(before.nm_connection_uuid,after.nm_connection_uuid)
    def test_cellular_uuid_change_full_lifecycle(self):
        s=MemoryStore();b=MemoryBackend(s);p=Fixture();c=Controller(b,s)
        with patch.object(b,'detect_uplink',side_effect=lambda:detect(p)):
            self.assertEqual(c.start('internet')['uplink_type'],'CELLULAR');c.stop()
            p.device['uuid']='f0000003-0000-4000-8000-000000000003'
            self.assertEqual(c.start('internet')['uplink_type'],'CELLULAR');c.stop()
        self.assertIsNone(s.load())
    def test_ethernet_normal_and_unusual_names(self):
        for name in ('enp2s0','uplink-west.7','lan_odd-1'):
            with self.subTest(name=name):
                v=detect(Fixture(name,'802-3-ethernet',1,name));self.assertTrue(v.supported);self.assertEqual(v.type,'ETHERNET')
    def test_private_upstream_gateways(self):
        for gateway in ('192.168.1.1','10.20.0.1','172.20.0.1'):
            p=Fixture('lan7','802-3-ethernet',1,'lan7')
            for row in p.routes.values():row[0]['gateway']=gateway
            self.assertEqual(detect(p).gateway,gateway);self.assertTrue(detect(p).supported)
    def test_disconnected_or_wrong_nm_mapping_rejected(self):
        for key,value in [('state',30),('connection_state',1),('ip_interface','wrong0')]:
            p=Fixture();p.device[key]=value;self.assertFalse(detect(p).supported)
    def test_virtual_uplinks_never_fall_back(self):
        for name in ('tailscale0','zt1234','docker0','br-aaaa','veth99','lo','tun0','tap0','wg0','aaghp12345678'):
            p=Fixture(name,'802-3-ethernet',1,name)
            self.assertEqual(detect(p).reason,'VIRTUAL_UPLINK_REJECTED')
    def test_disguised_virtual_and_unknown_nm_types_rejected(self):
        p=Fixture('ordinary','802-3-ethernet',1,'ordinary');p.linkdata['linkinfo']={'info_kind':'tun'}
        self.assertFalse(detect(p).supported)
        p=Fixture('ordinary','vpn',16,'ordinary');self.assertFalse(detect(p).supported)
    def test_policy_route_and_metric_come_from_route_lookup(self):
        p=Fixture();v=detect(p);self.assertEqual((v.table,v.route_metric),('201',73))
        self.assertEqual([ip for ip,k in p.calls if not k],list(PROBES))
    def test_split_public_paths_refused(self):
        p=Fixture();p.routes[PROBES[1]][0]['dev']='other0'
        self.assertEqual(detect(p).reason,'SPLIT_PUBLIC_ROUTES')
    def test_no_route_is_safe(self):
        p=Fixture();p.routes={ip:[] for ip in PROBES};self.assertFalse(detect(p).supported)
    def test_route_changes_between_invocations(self):
        p=Fixture();first=detect(p)
        p=Fixture('lan7','802-3-ethernet',1,'lan7');second=detect(p)
        self.assertTrue(second.supported)
        with self.assertRaisesRegex(ValueError,'UPLINK_CHANGED'):require_same(first,second)
    def test_forward_policy_route_checked_not_assumed(self):
        p=Fixture();forwarded_path(p,'cell42','aaghp12345678')
        self.assertTrue(all(k=={'source':'10.77.0.2','vif':'aaghp12345678'} for _,k in p.calls))
        with self.assertRaisesRegex(ValueError,'FORWARD_ROUTE_MISMATCH'):forwarded_path(p,'other','aaghp12345678')
    def test_errors_and_names_are_sanitized(self):
        p=Fixture();p.device['name']='provider\nSECRET_COMMAND\u202ename'
        self.assertNotIn('\n',detect(p).nm_connection_name);self.assertNotIn('\u202e',detect(p).nm_connection_name)
        with patch.object(p,'nm',side_effect=RuntimeError('sensitive error body')):
            self.assertNotIn('sensitive',str(detect(p).public()))
    def test_no_uplink_identity_in_binding(self):
        self.assertEqual(set(binding.UNBOUND),{'schema','wifi_interface','phy'})
        with self.assertRaises(ValueError):binding.validate(dict(binding.UNBOUND,cellular_uuid='anything'))
    def test_no_hardcoded_upstream_in_runtime(self):
        root=Path(__file__).resolve().parents[1]/'lib/aag_hotspot'
        for name in ('policy.py','backend.py','controller.py','client.py','cli.py','gui.py','binding.py','ownership.py'):
            source=(root/name).read_text()
            for token in ('CELL_UUID','wwan0','wwan0mbim0','019 - eSim','FM350'):
                self.assertNotIn(token,source,name)


class DynamicPresentationTests(unittest.TestCase):
    def test_cli_adds_fields_without_losing_old_keys(self):
        import contextlib,io
        from aag_hotspot import cli,client
        value={'mode':'internet','health':'OK','clients':0,'client_details':[]} | detect(Fixture()).status()
        with patch.object(client,'status',return_value=value),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['status']),0)
        for key in ('MODE','UPLINK','CLIENTS','UPLINK_TYPE','UPLINK_INTERFACE','UPLINK_CONNECTION','UPLINK_DEVICE','UPLINK_SUPPORTED','UPLINK_REASON'):
            self.assertIn(key+'=',output.getvalue())
    def test_bilingual_gui_reports_type_and_name_without_uuid(self):
        from aag_hotspot import gui,i18n
        previous=i18n.language();self.addCleanup(i18n.set_language,previous)
        for code in ('en','he'):
            i18n.set_language(code)
            for p in (Fixture(),Fixture('lan7','802-3-ethernet',1,'lan7')):
                v=detect(p);text=gui.presentation(v.status())['source']
                self.assertIn(v.nm_connection_name,text);self.assertNotIn(v.nm_connection_uuid,text)
    def test_doctor_dynamic_even_while_local_does_not_need_uplink(self):
        from aag_hotspot import client,uplink
        selected=detect(Fixture('lan7','802-3-ethernet',1,'lan7'))
        value={'installed':True,'configured':True,'uplink_type':'NONE_REQUIRED'}
        with patch.object(client,'status',return_value=value),patch.object(uplink,'detect',return_value=selected),patch.object(client,'probe',return_value={'ok':True,'stdout':RADIO}):
            result=client.doctor()
        self.assertEqual(result['selected_public_uplink']['type'],'ETHERNET')
        self.assertTrue(result['checks']['uplink_supported']);self.assertFalse(result['checks']['cellular_public_route'])


class DynamicPolicyTests(unittest.TestCase):
    def test_egress_is_explicit_for_each_supported_type(self):
        for iface in ('cell42','odd-wired','wifi7'):
            r='\n'.join(policy.rules('aaghp12345678','internet',iface)['forward_guard'])
            self.assertIn('oifname "'+iface+'" counter accept',r)
            self.assertIn('iifname "'+iface+'" oifname "aaghp12345678"',r)
            self.assertNotIn('192.168.0.0/16',r);self.assertNotIn('10.0.0.0/8',r)
            self.assertTrue(r.endswith('oifname "aaghp12345678" counter drop'))
    def test_reject_injection_and_virtual_names(self):
        for iface in ('bad"; flush ruleset','bad\nname','a'*16,'docker0','tailscale0','ztab','tun0',None):
            with self.assertRaises(ValueError):policy.rules('aaghp12345678','internet',iface)
    def test_local_no_route_ipv4_ipv6_and_dns(self):
        r=policy.rules('aaghp12345678','local');forward=r['forward_guard']
        self.assertEqual(sum(line.endswith('accept') for line in forward),1)
        self.assertEqual(sum('meta nfproto ipv6' in line and 'drop' in line for line in forward),2)
        self.assertTrue(any('udp dport 53 counter drop' in line for line in r['input_guard']))
    def test_local_lifecycle_does_not_probe_any_uplink(self):
        for description in ('no routes','cellular disconnected','Ethernet disconnected','Wi-Fi disconnected'):
            with self.subTest(description=description):
                s=MemoryStore();b=MemoryBackend(s);c=Controller(b,s)
                with patch.object(b,'detect_uplink',side_effect=AssertionError('Local must not inspect an uplink')):
                    v=c.start('local');self.assertEqual(v['uplink_type'],'NONE_REQUIRED');self.assertTrue(c.tick())
                c.stop();self.assertIsNone(s.load())
    def test_internet_local_downgrade_after_uplink_disappears(self):
        s=MemoryStore();b=MemoryBackend(s);c=Controller(b,s);c.start('internet');b.uplink=None
        self.assertEqual(c.start('local')['mode'],'local');self.assertTrue(c.tick());c.stop()
    def test_health_route_change_stops_owned_resources(self):
        s=MemoryStore();b=MemoryBackend(s);c=Controller(b,s);c.start('internet');b.uplink='tailscale0'
        self.assertFalse(c.tick());self.assertIsNone(s.load());self.assertIsNone(b.t)


class WifiArchitectureTests(unittest.TestCase):
    def test_advertised_capability_not_production_readiness(self):
        self.assertTrue(wifi.capability(RADIO)['sta_ap'])
        p=Fixture('wlan0','802-11-wireless',2,'wlan0')
        self.assertFalse(detect(p).supported);self.assertEqual(detect(p).reason,'WIFI_STA_AP_UNVALIDATED')
        self.assertTrue(detect(p,allow_wifi_validation=True).supported)
    def test_same_channel_uses_sta_frequency_never_forces_six(self):
        v=wifi.plan(RADIO,sta='wlan0',sta_info=STA_INFO,sta_link=STA_LINK,phy=0)
        self.assertEqual((v.channel,v.frequency,v.band),(36,5180,'a'));self.assertTrue(v.same_channel)
    def test_unavailable_regulatory_and_incompatible_phy_refused(self):
        for text,link,phy in ((RADIO.replace('(22.0 dBm)','(no IR)'),STA_LINK,0),(RADIO,STA_LINK.replace('5180','5260'),0),(RADIO,STA_LINK,1)):
            with self.assertRaises(ValueError):wifi.plan(text,sta='wlan0',sta_info=STA_INFO,sta_link=link,phy=phy)
    def test_combination_limits_and_unsupported_driver(self):
        for value in ('',RADIO.replace('total <= 4','total <= 2'),RADIO.replace('managed','monitor'),RADIO.replace('#{ AP, P2P-client } <= 1','#{ AP, P2P-client } <= 0')):
            self.assertFalse(wifi.capability(value,p2p_devices=1)['sta_ap'])
    def test_driver_without_p2p_device_needs_only_two_slots(self):
        text='valid interface combinations:\n * #{ managed, AP } <= 2, total <= 2, #channels <= 1'
        self.assertTrue(wifi.capability(text)['sta_ap'])
        self.assertFalse(wifi.capability(text,p2p_devices=1)['sta_ap'])

    def test_unconnected_sta_rejected(self):
        with self.assertRaises(ValueError):wifi.plan(RADIO,sta='wlan0',sta_info=STA_INFO,sta_link='Not connected.',phy=0)
    def test_sta_start_preserves_radio_and_upstream_autoconnect(self):
        s=MemoryStore();b=MemoryBackend(s);c=Controller(b,s);b.rv='enabled'
        plan=wifi.plan(RADIO,sta='wlan0',sta_info=STA_INFO,sta_link=STA_LINK,phy=0)
        with patch.object(b,'preflight',return_value=(b.detect_uplink(),plan)):
            c.start('internet');self.assertFalse(s.data['radio_touched']);self.assertFalse(s.data['auto_touched']);c.stop()
        self.assertFalse(any(call in ('radio_off','radio_on','auto_off','auto_on') for call in b.calls))
        self.assertEqual(b.rv,'enabled')


if __name__=='__main__':unittest.main()
