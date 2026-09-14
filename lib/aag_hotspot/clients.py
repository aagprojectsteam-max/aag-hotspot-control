"""Read-only AP station/lease join. Never discover clients on other interfaces."""
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from .ownership import Backend as InspectionBackend, ENV

MAX_CLIENTS = 256
MAX_PUBLIC_BYTES = 262144
CLIENT_TTL = 15.0
SUBNET = ipaddress.ip_network('10.77.0.0/24')
MAC = r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}'


class Probe(InspectionBackend):
    """Optional display reads cannot hold the operation lock indefinitely."""
    def __init__(self): self.deadline = time.monotonic() + 6
    def run(self, argv):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise ValueError('CLIENT_PROBE_TIMEOUT')
        result = subprocess.run(argv, capture_output=True, text=True, timeout=min(2, remaining), env=ENV)
        if result.returncode: raise ValueError('CLIENT_PROBE_UNAVAILABLE')
        return result.stdout.strip()


def mac_address(value):
    if not isinstance(value, str): return None
    value = value.lower()
    if not re.fullmatch(MAC, value) or int(value[:2], 16) & 1 or value == '00:00:00:00:00:00': return None
    return value


def ipv4_address(value):
    try: address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError): return None
    if address not in SUBNET or address in (SUBNET.network_address, SUBNET.broadcast_address, ipaddress.IPv4Address('10.77.0.1')):
        return None
    return str(address)


def hostname(value):
    # Never reverse-resolve, infer from MAC vendors, render markup, or accept
    # control/bidi characters supplied by an untrusted DHCP client.
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', value) else None


def stations(text, interface):
    result = {}
    for block in re.split(r'(?=^Station )', text, flags=re.M):
        if not block.strip(): continue
        header = re.match(r'^Station (' + MAC + r') \(on ([a-zA-Z0-9]+)\)', block, re.I)
        if not header: raise ValueError('INVALID_STATION_DATA')
        mac = mac_address(header[1])
        if not mac or header[2] != interface: raise ValueError('INVALID_STATION_SCOPE')
        if re.search(r'^\s*associated:\s*no\s*$', block, re.M): continue
        signal = re.search(r'^\s*signal:\s*(-?\d+)', block, re.M)
        duration = re.search(r'^\s*connected time:\s*(\d+)\s+seconds\s*$', block, re.M)
        dbm = int(signal[1]) if signal else None
        result[mac] = {'mac': mac, 'signal_dbm': dbm if dbm is not None and -127 <= dbm <= 0 else None,
                       'connected_seconds': int(duration[1]) if duration else None}
    if len(result) > MAX_CLIENTS: raise ValueError('STATION_LIMIT_EXCEEDED')
    return result


def leases(text, now):
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 5: continue
        expiry, mac, address, name, _ = fields
        mac, address = mac_address(mac), ipv4_address(address)
        if not expiry.isdecimal() or not mac or not address: continue
        expiry = int(expiry)
        if expiry != 0 and expiry <= now: continue
        candidate = {'ipv4': address, 'hostname': hostname(name), 'expiry': expiry or float('inf')}
        if mac not in result or result[mac]['expiry'] < candidate['expiry']: result[mac] = candidate
    # Ambiguous leases cannot establish which MAC currently owns an address.
    addresses = [record['ipv4'] for record in result.values()]
    return {mac: record for mac, record in result.items() if addresses.count(record['ipv4']) == 1}


def neighbors(text, interface):
    result = {}
    rows = json.loads(text)
    if not isinstance(rows, list): raise ValueError('INVALID_NEIGHBOR_DATA')
    for row in rows:
        if not isinstance(row, dict) or row.get('dev') != interface or row.get('state') != ['REACHABLE']: continue
        mac, address = mac_address(row.get('lladdr')), ipv4_address(row.get('dst'))
        if mac and address: result.setdefault(mac, set()).add(address)
    return {mac: next(iter(values)) for mac, values in result.items() if len(values) == 1}


def merge(station_text, lease_text, neighbor_text, interface, now):
    associated, assigned, reachable = stations(station_text, interface), leases(lease_text, now), neighbors(neighbor_text, interface)
    rows = []
    for mac, record in sorted(associated.items()):
        lease = assigned.get(mac)
        address = lease['ipv4'] if lease else reachable.get(mac)
        rows.append(record | {'ipv4': address, 'hostname': lease['hostname'] if lease else None,
                             'ip_source': 'dhcp_lease' if lease else ('neighbor_reachable' if address else None)})
    return rows


def read_leases(interface):
    if not re.fullmatch(r'aaghp[0-9a-f]{8}', interface): raise ValueError('INVALID_AP_INTERFACE')
    parent = Path('/var/lib/NetworkManager')
    metadata = parent.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError('UNTRUSTED_LEASE_DIRECTORY')
    path = parent / ('dnsmasq-' + interface + '.leases')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r', encoding='utf-8', errors='replace') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_mode & 0o022
                or metadata.st_size > 1048576):
            raise ValueError('UNTRUSTED_LEASE_FILE')
        text = stream.read(1048577)
        if len(text) > 1048576: raise ValueError('LEASE_FILE_TOO_LARGE')
        return text


def snapshot(backend, owner):
    """Caller holds the existing operation lock; no extra helper/privilege API."""
    unavailable = {'clients': None, 'client_count': None, 'client_details': [],
                   'client_data_status': 'UNAVAILABLE', 'clients_updated_monotonic': time.monotonic()}
    try:
        if not re.fullmatch(r'aaghp[0-9a-f]{8}', owner.vif): return unavailable
        device = backend.interface(owner)
        if (not device or device.get('mode') != 'AP' or device.get('ifindex') != owner.ifindex
                or device.get('mac') != owner.mac or backend.active().get(owner.profile_uuid) != [owner.vif]):
            return unavailable
        station_text = backend.run(['/usr/sbin/iw', 'dev', owner.vif, 'station', 'dump'])
        warnings = []
        try: lease_text = read_leases(owner.vif)
        except FileNotFoundError: lease_text = ''
        except (OSError, ValueError): lease_text = ''; warnings.append('LEASES_UNAVAILABLE')
        try:
            neighbor_text = backend.run(['/usr/sbin/ip', '-j', '-4', 'neigh', 'show', 'dev', owner.vif])
            neighbors(neighbor_text, owner.vif)
        except Exception: neighbor_text = '[]'; warnings.append('NEIGHBORS_UNAVAILABLE')
        rows = merge(station_text, lease_text, neighbor_text, owner.vif, time.time())
        return {'clients': len(rows), 'client_count': len(rows), 'client_details': rows,
                'client_data_status': 'DEGRADED' if warnings else 'OK', 'client_warnings': warnings,
                'clients_updated_monotonic': time.monotonic()}
    except Exception:
        # Optional visibility failures never trigger a networking rollback and
        # never expose raw subprocess or lease data in diagnostics.
        return unavailable


def expire(value, now=None):
    """Never retain a previous address through a mode transition or stalled watch."""
    phase = value.get('phase')
    if phase == 'off':
        value.update(clients=0, client_count=0, client_details=[], client_data_status='OFF')
    elif phase != 'active' or value.get('health') != 'OK':
        value.update(clients=None, client_count=None, client_details=[], client_data_status='UNAVAILABLE')
    else:
        stamp = value.get('clients_updated_monotonic')
        age = (time.monotonic() if now is None else now) - stamp if type(stamp) in (int, float) else None
        if age is None or not 0 <= age <= CLIENT_TTL:
            value.update(clients=None, client_count=None, client_details=[], client_data_status='STALE')
    return value
