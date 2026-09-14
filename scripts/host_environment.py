"""Read-only supported-environment checks and installer binding discovery."""
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot.binding import validate, valid_uuid
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'NM_CLI_COLOR': 'never'}


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20, env=ENV)
    except (OSError, subprocess.TimeoutExpired): raise RuntimeError('Required environment probe unavailable or timed out') from None
    if result.returncode: raise RuntimeError('Environment probe failed: ' + Path(args[0]).name)
    return result.stdout.strip()


def detect(wifi_interface=None):
    info = platform.freedesktop_os_release()
    if info.get('ID') != 'ubuntu' or info.get('VERSION_ID') != '26.04' or platform.machine() != 'x86_64':
        raise RuntimeError('This preview supports Ubuntu 26.04 x86_64 only; see docs/COMPATIBILITY.md')
    required = ('nmcli','NetworkManager','iw','ip','nft','iptables-save','ip6tables-save','dnsmasq','pkexec','systemctl','ss','sysctl','update-desktop-database')
    missing = [name for name in required if not shutil.which(name, path=ENV['PATH'])]
    if missing: raise RuntimeError('Missing dependencies: ' + ', '.join(missing) + '; see README dependency command')
    run(['/usr/bin/python3','-I','-c','import gi;gi.require_version("Gtk","4.0");gi.require_version("Adw","1");from gi.repository import Gtk,Adw,Gio;assert Adw.get_minor_version() >= 8'])
    if run(['/usr/bin/nmcli','-g','RUNNING','general','status']) != 'running':
        raise RuntimeError('NetworkManager must already be running; installer will not restart it')
    if not re.search(r'\b1\.54\.',run(['/usr/bin/nmcli','--version'])):
        raise RuntimeError('This preview requires the tested NetworkManager 1.54 family')
    if not re.search(r'^firewall-backend=iptables$',run(['/usr/sbin/NetworkManager','--print-config']),re.M):
        raise RuntimeError('Requires existing NetworkManager firewall-backend=iptables; global configuration is preserved')
    if run(['/usr/sbin/sysctl','-n','net.ipv4.ip_forward']) != '1':
        raise RuntimeError('Requires existing IPv4 forwarding=1; installer will not change global forwarding')
    records=[];phy=None;current=None
    for line in run(['/usr/sbin/iw','dev']).splitlines():
        m=re.fullmatch(r'phy#(\d+)',line.strip())
        if m:phy=int(m[1])
        m=re.fullmatch(r'Interface (\S+)',line.strip())
        if m:current={'wifi_interface':m[1],'phy':phy};records.append(current)
        if line.strip().startswith('type ') and current is not None:current['type']=line.strip().split()[1]
    candidates=[x for x in records if x.get('type')=='managed' and (wifi_interface is None or x['wifi_interface']==wifi_interface)]
    if len(candidates)!=1: raise RuntimeError('Select one existing Wi-Fi station interface with --wifi-interface; no interface will be created')
    selected=candidates[0]
    radio=run(['/usr/sbin/iw','phy','phy'+str(selected['phy']),'info'])
    if not re.search(r'^\s*\* AP\s*$',radio,re.M):raise RuntimeError('Wi-Fi hardware does not advertise AP mode')
    channel=re.search(r'^\s*\* 2437(?:\.0)? MHz \[6\].*$',radio,re.M)
    if not channel or any(word in channel[0].lower() for word in ('disabled','no ir','radar')):
        raise RuntimeError('2.4 GHz channel 6 is unavailable for AP initiation under the current regulatory state')
    if not re.search(r'^\s*\* #\{.*managed.*AP.*<=\s*2|^\s*\* #\{.*AP.*managed.*<=\s*2',radio,re.M):
        # Driver combinations vary in layout; activation still performs authoritative checks.
        if 'valid interface combinations:' not in radio:raise RuntimeError('Driver does not advertise virtual-interface combinations')
    protected=set();cellular=[]
    for line in run(['/usr/bin/nmcli','-t','-f','UUID,TYPE,NAME','connection','show']).splitlines():
        uid,kind,name=line.split(':',2)
        if not valid_uuid(uid):raise RuntimeError('Invalid NetworkManager inventory')
        if name=='Hotspot':protected.add(uid)
    for line in run(['/usr/bin/nmcli','-t','-f','UUID,TYPE,DEVICE','connection','show','--active']).splitlines():
        uid,kind,device=line.split(':',2)
        if kind=='gsm' and device=='wwan0mbim0':cellular.append(uid)
    if len(cellular)>1:raise RuntimeError('Ambiguous cellular profile; existing connections are preserved')
    cell=cellular[0] if cellular else None
    if cell:protected.add(cell)
    return validate({'schema':1,'wifi_interface':selected['wifi_interface'],'phy':selected['phy'],
                     'cellular_uuid':cell,'protected_uuids':sorted(protected)})
