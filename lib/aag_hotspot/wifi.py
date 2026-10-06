"""Conservative radio/channel planning; capability is not live validation."""
from dataclasses import asdict,dataclass
import re
from .uplink import interface_name


@dataclass(frozen=True)
class Plan:
    channel: int = 6
    frequency: int = 2437
    band: str = 'bg'
    sta_interface: str | None = None
    sta_frequency: int | None = None
    same_channel: bool = False

    def public(self):return asdict(self)


def channel(info,frequency):
    m=re.search(r'^\s*\* '+str(frequency)+r'(?:\.0)? MHz \[(\d+)\](.*)$',info,re.M)
    if not m or any(v in m[2].lower() for v in ('disabled','no ir','radar')):
        raise ValueError('WIFI_CHANNEL_UNAVAILABLE')
    if 2412<=frequency<=2472:band='bg'
    elif 5000<=frequency<5900:band='a'
    else:raise ValueError('WIFI_BAND_UNSUPPORTED')
    return int(m[1]),band


def capability(info, p2p_devices=0):
    section=info.split('valid interface combinations:',1)
    if len(section)!=2:return {'sta_ap':False,'same_channel':None,'reason':'NO_COMBINATIONS'}
    for block in re.split(r'\n\s*\*',section[1]):
        groups=re.findall(r'#\{([^}]+)\}\s*<=\s*(\d+)',block)
        total=re.search(r'total\s*<=\s*(\d+)',block)
        channels=re.search(r'#channels\s*<=\s*(\d+)',block)
        needed={'managed':1,'AP':1}
        if p2p_devices:needed['P2P-device']=p2p_devices
        if not total or not channels or int(total[1])<sum(needed.values()):continue
        covered=set();valid=True
        for types,limit in groups:
            types={x.strip() for x in types.split(',')};covered|=types
            if sum(count for kind,count in needed.items() if kind in types)>int(limit):valid=False
        if valid and set(needed)<=covered:
            # Always choose the current STA channel, even if hardware allows more.
            return {'sta_ap':True,'same_channel':int(channels[1])==1,'reason':'ADVERTISED_ONLY_UNVALIDATED'}
    return {'sta_ap':False,'same_channel':None,'reason':'NO_SAFE_COMBINATION'}


def station(info,link):
    phy=re.search(r'^\s*wiphy (\d+)\s*$',info,re.M)
    mode=re.search(r'^\s*type (\S+)\s*$',info,re.M)
    freq=re.search(r'^\s*freq: (\d+)\s*$',link,re.M)
    if not phy or not mode or mode[1]!='managed' or not freq or not link.startswith('Connected to '):
        raise ValueError('WIFI_STA_NOT_CONNECTED')
    return int(phy[1]),int(freq[1])


def plan(info,*,sta=None,sta_info=None,sta_link=None,phy=None,p2p_devices=0):
    if sta is None:
        ch,band=channel(info,2437);return Plan(ch,2437,band)
    if not interface_name(sta) or not capability(info,p2p_devices)['sta_ap']:raise ValueError('WIFI_STA_AP_UNSUPPORTED')
    actual_phy,freq=station(sta_info,sta_link)
    if actual_phy!=phy:raise ValueError('WIFI_RADIO_MISMATCH')
    ch,band=channel(info,freq)
    return Plan(ch,freq,band,sta,freq,True)


def from_dict(value):
    if not isinstance(value,dict) or set(value)!=set(Plan().public()):raise ValueError('Invalid radio plan')
    result=Plan(**value)
    if (type(result.channel)is not int or not 1<=result.channel<=196 or type(result.frequency)is not int
        or result.band not in ('bg','a') or type(result.same_channel)is not bool
        or (result.sta_interface is not None and not interface_name(result.sta_interface))):
        raise ValueError('Invalid radio plan')
    return result
