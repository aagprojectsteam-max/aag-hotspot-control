#!/usr/bin/python3
"""Synthetic L3 firewall tests INSIDE a disposable network namespace only.

No Wi-Fi device/profile/association is used. These tests never establish physical
client validation. Execute through validate-production-local.py, which unshares
the network namespace before this file can create any virtual links.
"""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from aag_hotspot.policy import nft_program

VIF = 'aaghp12345678'
OWNER = SimpleNamespace(vif=VIF, table='aag_hotspot', marker='AAG-Hotspot-Control session=f0000001-0000-4000-8000-000000000001')


def command(argv, text=None):
    r = subprocess.run(argv, input=text, capture_output=True, text=True, timeout=10)
    if r.returncode: raise RuntimeError(str(argv) + ': ' + r.stderr)
    return r.stdout


def checksum(data):
    if len(data) % 2: data += b'\0'
    total = sum(struct.unpack('!' + 'H' * (len(data)//2), data))
    while total >> 16: total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def frame(mac_src, mac_dst, source, dest, sport, dport, payload, ipv6=False):
    src = socket.inet_pton(socket.AF_INET6 if ipv6 else socket.AF_INET, source)
    dst = socket.inet_pton(socket.AF_INET6 if ipv6 else socket.AF_INET, dest)
    udp = struct.pack('!HHHH', sport, dport, 8 + len(payload), 0) + payload
    if ipv6:
        pseudo = src + dst + struct.pack('!I3xB', len(udp), 17)
        crc = checksum(pseudo + udp) or 65535
        udp = udp[:6] + struct.pack('!H', crc) + udp[8:]
        ip = struct.pack('!IHBB', 6 << 28, len(udp), 17, 64) + src + dst
    else:
        ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), 7, 0, 64, 17, 0, src, dst)
        ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
    return bytes.fromhex(mac_dst.replace(':', '')) + bytes.fromhex(mac_src.replace(':', '')) + struct.pack('!H', 0x86dd if ipv6 else 0x0800) + ip + udp


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise RuntimeError('Namespace test runner required')
    initial_namespace = sys.argv[1]
    if os.readlink('/proc/self/ns/net') == initial_namespace:
        raise RuntimeError('REFUSED: still in the production network namespace')
    names = json.loads(command(['ip', '-j', 'link', 'show']))
    if [x['ifname'] for x in names] != ['lo']:
        raise RuntimeError('REFUSED: disposable namespace is not empty')
    command(['ip', 'link', 'set', 'lo', 'up'])
    command(['sysctl', '-q', '-w', 'net.ipv4.ip_forward=1', 'net.ipv6.conf.all.forwarding=1'])
    pairs = [(VIF, 'ap_peer', '10.77.0.1/24', '10.77.0.2'),
             ('cell7', 'ww_peer', '198.18.0.1/24', '198.18.0.2'),
             ('tailscale0', 'ts_peer', '203.0.113.1/24', '203.0.113.2'),
             ('docker0', 'dk_peer', '172.17.0.1/24', '172.17.0.2'),
             ('future0', 'ft_peer', '198.19.0.1/24', '198.19.0.2'),
             ('private1', 'pv_peer', '192.168.23.1/24', '192.168.23.2'),
             ('private2', 'px_peer', '10.23.0.1/24', '10.23.0.2'),
             ('private3', 'py_peer', '172.23.0.1/24', '172.23.0.2'),
             ('ztfixture', 'zt_peer', '10.244.0.1/24', '10.244.0.2'),
             ('lan0', 'ln_peer', '192.0.2.1/24', '192.0.2.2')]
    macs, peers = {}, {}
    for name, peer, addr, neighbor in pairs:
        command(['ip', 'link', 'add', name, 'type', 'veth', 'peer', 'name', peer])
        for dev in (name, peer):
            command(['ip', 'link', 'set', dev, 'up'])
            macs[dev] = json.loads(command(['ip', '-j', 'link', 'show', 'dev', dev]))[0]['address']
        command(['ip', 'addr', 'add', addr, 'dev', name])
        command(['ip', 'neigh', 'replace', neighbor, 'lladdr', macs[peer], 'nud', 'permanent', 'dev', name])
        peers[name] = peer
    command(['ip', 'neigh', 'replace', '10.77.0.3', 'lladdr', macs['ap_peer'], 'nud', 'permanent', 'dev', VIF])
    command(['ip', '-6', 'addr', 'add', '2001:db8:77::1/64', 'dev', VIF, 'nodad'])
    command(['ip', '-6', 'addr', 'add', '2001:db8:18::1/64', 'dev', 'cell7', 'nodad'])
    command(['ip', '-6', 'neigh', 'replace', '2001:db8:18::2', 'lladdr', macs['ww_peer'], 'nud', 'permanent', 'dev', 'cell7'])
    # Deliberately permissive later chain models NM accepts: earlier AAG drops
    # must still win, regardless of route/NAT and established connection state.
    command(['nft', '-f', '-'], 'add table inet later\nadd chain inet later f { type filter hook forward priority 0; policy accept; }\nadd rule inet later f counter accept\n')
    command(['nft', '-f', '-'], 'add table ip fixture_nat\nadd chain ip fixture_nat p { type nat hook prerouting priority -100; }\nadd rule ip fixture_nat p ip daddr 10.77.0.1 udp dport 9000 dnat to 172.17.0.2:9000\n')
    command(['nft', '--check', '-f', '-'], nft_program(OWNER, 'local', True))
    command(['nft', '-f', '-'], nft_program(OWNER, 'local', True))
    results = {}
    sockets = {}
    for _, peer, _, _ in pairs:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        s.bind((peer, 0)); s.setblocking(False); sockets[peer] = s
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); dns.bind(('10.77.0.1', 53)); dns.setblocking(False)
    beep = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); beep.bind(('0.0.0.0', 36475)); beep.setblocking(False)
    marker_id = 0
    def drain(s):
        while True:
            try: s.recvfrom(65535)
            except BlockingIOError: return
    def received(s, marker):
        until = time.monotonic() + 0.22
        while time.monotonic() < until:
            try:
                content, address = s.recvfrom(65535)
                if s.family == socket.AF_PACKET and address[2] == socket.PACKET_OUTGOING: continue
                if marker in content: return True
            except BlockingIOError: time.sleep(0.005)
        return False
    def packet(label, target, dest, allowed, incoming=VIF, source='10.77.0.2', sport=40000, dport=65000, ipv6=False):
        nonlocal marker_id
        marker_id += 1; marker = ('AAG-ISOLATED-' + str(marker_id)).encode()
        s = target if isinstance(target, socket.socket) else sockets[peers[target]]
        drain(s)
        peer = peers[incoming]
        sockets[peer].send(frame(macs[peer], macs[incoming], source, dest, sport, dport, marker, ipv6))
        observed = received(s, marker)
        results[label] = {'expected_delivery': allowed, 'observed_delivery': observed, 'pass': observed == allowed}
    packet('local_wwan_block', 'cell7', '198.18.0.2', False)
    packet('local_tailnet_block', 'tailscale0', '203.0.113.2', False)
    packet('local_docker_block', 'docker0', '172.17.0.2', False)
    packet('local_future_interface_block', 'future0', '198.19.0.2', False)
    packet('local_DNAT_published_port_block', 'docker0', '10.77.0.1', False, dport=9000)
    packet('local_IPv6_forwarding_block', 'cell7', '2001:db8:18::2', False, source='2001:db8:77::2', ipv6=True)
    packet('local_recursive_DNS_block', dns, '10.77.0.1', False, dport=53)
    packet('local_BeeBEEP_UDP_allow', beep, '10.77.0.1', True, dport=36475)
    packet('local_same_AP_subnet_allow', VIF, '10.77.0.3', True)
    packet('unrelated_forwarding_preserved', 'cell7', '198.18.0.2', True, incoming='lan0', source='192.0.2.2')
    command(['nft', '-f', '-'], nft_program(OWNER, 'internet', uplink='cell7'))
    packet('internet_wwan_allow', 'cell7', '198.18.0.2', True)
    packet('internet_established_return_allow', VIF, '10.77.0.2', True, incoming='cell7', source='198.18.0.2', sport=65000, dport=40000)
    packet('internet_tailnet_block', 'tailscale0', '203.0.113.2', False)
    packet('internet_docker_block', 'docker0', '172.17.0.2', False)
    packet('internet_wrong_egress_block', 'future0', '198.19.0.2', False)
    packet('internet_source_spoof_block', 'cell7', '198.18.0.2', False, source='192.0.2.2')
    packet('internet_IPv6_block', 'cell7', '2001:db8:18::2', False, source='2001:db8:77::2', ipv6=True)
    packet('internet_zerotier_block', 'ztfixture', '10.244.0.2', False)
    for name,dest in [('private1','192.168.23.2'),('private2','10.23.0.2'),('private3','172.23.0.2')]:
        command(['nft','-f','-'],nft_program(OWNER,'internet',uplink=name))
        packet('internet_RFC1918_'+name,name,dest,True)
        packet('internet_RFC1918_protect_docker_'+name,'docker0','172.17.0.2',False)
    command(['nft','-f','-'],nft_program(OWNER,'internet',uplink='cell7'))
    packet('internet_DNS_listener_allow', dns, '10.77.0.1', True, dport=53)
    dns.sendto(b'initial-response', ('10.77.0.2', 40000))
    command(['nft', '-f', '-'], nft_program(OWNER, 'local'))
    packet('downgrade_existing_flow_out_block', 'cell7', '198.18.0.2', False)
    packet('downgrade_established_return_block', VIF, '10.77.0.2', False, incoming='cell7', source='198.18.0.2', sport=65000, dport=40000)
    packet('downgrade_existing_DNS_request_block', dns, '10.77.0.1', False, dport=53)
    drain(sockets['ap_peer'])
    denied = False
    try: dns.sendto(b'late-DNS-response', ('10.77.0.2', 40000))
    except PermissionError: denied = True  # nft output drop can synchronously return EPERM.
    results['downgrade_DNS_response_block'] = {'send_denied': denied, 'pass': not received(sockets['ap_peer'], b'late-DNS-response')}
    command(['ip', 'route', 'add', 'default', 'via', '198.19.0.2', 'dev', 'future0'])
    command(['ip', 'neigh', 'replace', '198.19.0.2', 'lladdr', macs['ft_peer'], 'nud', 'permanent', 'dev', 'future0'])
    packet('local_new_default_route_block', 'future0', '8.8.8.8', False)
    command(['nft', '-f', '-'], nft_program(OWNER, 'blocked'))
    packet('off_barrier_local_service_block', beep, '10.77.0.1', False, dport=36475)
    print(json.dumps({'namespace': os.readlink('/proc/self/ns/net'), 'production_namespace': initial_namespace,
                      'synthetic_packets_only': True, 'physical_client_validation': 'NOT_TESTED',
                      'checks': results, 'passed': all(x['pass'] for x in results.values())}, indent=2))
    return 0 if all(x['pass'] for x in results.values()) else 1


if __name__ == '__main__': raise SystemExit(main())
