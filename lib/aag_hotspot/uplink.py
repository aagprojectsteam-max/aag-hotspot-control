"""Read-only kernel-route selection and NetworkManager classification.

Connection UUID/name are descriptive metadata, never eligibility. No interface
is chosen by prefix, default-route order, or a preferred provider/profile.
"""
from dataclasses import asdict, dataclass, replace
import ipaddress
import json
import re
import subprocess
import unicodedata

PROBES = ('1.1.1.1', '9.9.9.9')
ENV = {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'}


def interface_name(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}',value) is not None


def excluded_interface(value):
    return not interface_name(value) or value == 'lo' or value.startswith(
        ('aaghp','aaght','tailscale','zt','docker','br-','veth','tun','tap','wg','virbr'))


def display_name(value):
    return ''.join(c for c in str(value) if not unicodedata.category(c).startswith('C'))[:128]


@dataclass(frozen=True)
class Uplink:
    interface: str | None = None
    type: str = 'NONE'
    nm_device: str | None = None
    nm_connection_name: str | None = None
    nm_connection_uuid: str | None = None
    route_metric: int | None = None
    gateway: str | None = None
    source_address: str | None = None
    supported: bool = False
    validated: bool = False
    reason: str = 'NO_PUBLIC_ROUTE'
    table: str = 'main'

    def public(self): return asdict(self)
    def status(self):
        return {'uplink':self.interface, 'uplink_type':self.type,
                'uplink_interface':self.interface,'uplink_connection':self.nm_connection_name,
                'uplink_device':self.nm_device,'uplink_supported':self.supported,
                'uplink_reason':self.reason,'uplink_details':self.public()}

    def path(self):
        # UUID, display name and metric can change without changing the effective path.
        return self.interface,self.type,self.nm_device,self.gateway,self.source_address,self.table


LOCAL = Uplink(type='NONE_REQUIRED',supported=True,reason='LOCAL_UPLINK_NOT_REQUIRED')


class Probe:
    def read(self,args):
        result=subprocess.run(args,capture_output=True,text=True,timeout=4,env=ENV)
        if result.returncode: raise ValueError('UPLINK_PROBE_FAILED')
        return json.loads(result.stdout)

    def route(self,address,*,fibmatch=False,source=None,vif=None):
        args=['/usr/sbin/ip','-j','-4','route','get',address]
        if source is not None: args += ['from',source]
        if vif is not None: args += ['iif',vif]
        if fibmatch: args += ['fibmatch']
        return self.read(args)

    def link(self,interface):
        return self.read(['/usr/sbin/ip','-j','-d','link','show','dev',interface])[0]

    def nm(self,interface):
        from gi.repository import Gio,GLib
        bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
        def call(path,iface,method,args):
            return bus.call_sync('org.freedesktop.NetworkManager',path,iface,method,args,
                                 None,Gio.DBusCallFlags.NONE,3000,None).unpack()[0]
        path=call('/org/freedesktop/NetworkManager','org.freedesktop.NetworkManager',
                  'GetDeviceByIpIface',GLib.Variant('(s)',(interface,)))
        def props(path,iface):
            return call(path,'org.freedesktop.DBus.Properties','GetAll',GLib.Variant('(s)',(iface,)))
        device=props(path,'org.freedesktop.NetworkManager.Device')
        active=device.get('ActiveConnection','/')
        connection=props(active,'org.freedesktop.NetworkManager.Connection.Active') if active!='/' else {}
        return {'interface':device.get('Interface'),'ip_interface':device.get('IpInterface'),
                'device_type':device.get('DeviceType'),'state':device.get('State'),
                'connection_state':connection.get('State'),'connection_type':connection.get('Type'),
                'name':connection.get('Id'),'uuid':connection.get('Uuid')}


def detect(probe=None, *, allow_wifi_validation=False):
    probe=probe or Probe()
    try:
        paths=[probe.route(address) for address in PROBES]
        if any(not isinstance(rows,list) or len(rows)!=1 for rows in paths):return Uplink(reason='AMBIGUOUS_PUBLIC_ROUTE')
        first=paths[0][0];iface=first.get('dev')
        if any(row[0].get('dev')!=iface or row[0].get('gateway')!=first.get('gateway')
               or row[0].get('table','main')!=first.get('table','main') for row in paths):
            return Uplink(interface=iface if interface_name(iface) else None,type='UNSUPPORTED',reason='SPLIT_PUBLIC_ROUTES')
        if excluded_interface(iface):return Uplink(interface=iface if interface_name(iface) else None,type='UNSUPPORTED',reason='VIRTUAL_UPLINK_REJECTED')
        if first.get('type','unicast')!='unicast':return Uplink(reason='NON_UNICAST_ROUTE')
        source=str(ipaddress.IPv4Address(first['prefsrc'] if 'prefsrc' in first else first['src']))
        gateway=str(ipaddress.IPv4Address(first['gateway'])) if first.get('gateway') else None
        link=probe.link(iface)
        if (link.get('ifname')!=iface or link.get('master') or
            link.get('linkinfo',{}).get('info_kind') in ('bridge','veth','tun','wireguard','vxlan','vlan','macvlan','dummy','bond','team')):
            return Uplink(interface=iface,type='UNSUPPORTED',reason='VIRTUAL_UPLINK_REJECTED')
        nm=probe.nm(iface)
        if nm.get('ip_interface')!=iface or nm.get('state')!=100 or nm.get('connection_state')!=2:
            return Uplink(interface=iface,type='UNSUPPORTED',reason='NM_UPLINK_NOT_CONNECTED')
        kind={(8,'gsm'):'CELLULAR',(8,'cdma'):'CELLULAR',(1,'802-3-ethernet'):'ETHERNET',
              (2,'802-11-wireless'):'WIFI'}.get((nm.get('device_type'),nm.get('connection_type')),'UNSUPPORTED')
        if not interface_name(nm.get('interface')):return Uplink(interface=iface,type='UNSUPPORTED',reason='NM_DEVICE_IDENTITY_INVALID')
        metric=first.get('metric')
        try:
            fib=probe.route(PROBES[0],fibmatch=True)
            if len(fib)==1:metric=fib[0].get('metric',metric)
        except Exception:pass # Metric is diagnostic; route-get remains authoritative.
        supported=kind in ('CELLULAR','ETHERNET') or (kind=='WIFI' and allow_wifi_validation)
        reason=('ROUTE_AND_NM_CONFIRMED' if supported else
                'WIFI_STA_AP_UNVALIDATED' if kind=='WIFI' else 'NM_UPLINK_TYPE_UNSUPPORTED')
        return Uplink(iface,kind,nm['interface'],display_name(nm.get('name') or ''),nm.get('uuid'),
                      metric if type(metric)is int else None,gateway,source,supported,False,reason,str(first.get('table','main')))
    except Exception:
        # Never expose subprocess/DBus response bodies through public diagnostics.
        return Uplink(reason='UPLINK_INSPECTION_UNAVAILABLE')


def require_same(expected,current):
    if not current.supported or expected.path()!=current.path():
        raise ValueError('UPLINK_CHANGED: selected public path changed; turn off and retry')


def forwarded_path(probe,interface,vif):
    if not interface_name(interface) or not interface_name(vif):raise ValueError('Invalid interface')
    for address in PROBES:
        rows=probe.route(address,source='10.77.0.2',vif=vif)
        if len(rows)!=1 or rows[0].get('dev')!=interface:
            raise ValueError('FORWARD_ROUTE_MISMATCH: client policy route differs from selected uplink')
