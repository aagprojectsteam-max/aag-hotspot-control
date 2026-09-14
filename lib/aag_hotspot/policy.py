"""Pure, deterministic policy generation. No subprocess or network mutation."""
import hashlib
import re

SSID = 'AAG-Hotspot'
SUBNET = '10.77.0.0/24'
ADDRESS = '10.77.0.1'
TABLE = 'aag_hotspot'
from .binding import STA, PHY, CELL_UUID, PROTECTED_UUIDS
# Compatibility name used by regression fixtures; all baseline profiles are protected.
HOTSPOT_UUID = next((u for u in sorted(PROTECTED_UUIDS) if u != CELL_UUID), None)
SERVICE = 'aag-hotspot-watch.service'
MODES = ('local', 'internet', 'blocked')
CHAINS = ('input_guard', 'forward_guard', 'output_guard')


def rules(vif, mode):
    if not re.fullmatch(r'aaghp[0-9a-f]{8}', vif) or mode not in MODES:
        raise ValueError('Invalid owned interface or mode')
    i, o = f'iifname "{vif}"', f'oifname "{vif}"'
    ingress = [f'{i} meta nfproto ipv6 counter drop']
    forward = [f'{i} meta nfproto ipv6 counter drop', f'{o} meta nfproto ipv6 counter drop',
               f'{i} ip saddr != {SUBNET} counter drop']
    output = [f'{o} meta nfproto ipv6 counter drop']
    if mode != 'blocked':
        ingress += [f'{i} ip saddr {{ 0.0.0.0, {SUBNET} }} udp sport 68 udp dport 67 counter accept',
                    f'{i} ip saddr != {SUBNET} counter drop']
        # DNS rejection precedes established flows: a downgrade closes old DNS sessions too.
        if mode == 'local':
            ingress += [f'{i} udp dport 53 counter drop', f'{i} tcp dport 53 counter drop']
            output += [f'{o} udp sport 53 counter drop', f'{o} tcp sport 53 counter drop']
        else:
            ingress += [f'{i} ip daddr {ADDRESS} udp dport 53 counter accept',
                        f'{i} ip daddr {ADDRESS} tcp dport 53 counter accept']
        ingress += [f'{i} ip daddr {ADDRESS} ct state established,related counter accept',
                    f'{i} ip daddr {ADDRESS} ip protocol icmp counter accept',
                    f'{i} ip daddr {ADDRESS} tcp dport {{ 6475, 6476 }} counter accept',
                    f'{i} ip daddr {{ {ADDRESS}, 10.77.0.255, 255.255.255.255 }} udp dport 36475 counter accept',
                    f'{i} ip daddr 224.0.0.251 udp dport 5353 counter accept',
                    f'{i} ip daddr 224.0.0.252 udp dport 5355 counter accept']
        forward += [f'{i} {o} ip daddr {SUBNET} counter accept']
        if mode == 'internet':
            forward += [f'{i} ip daddr {{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 }} counter drop',
                        f'{i} oifname "wwan0" counter accept',
                        f'iifname "wwan0" {o} ip daddr {SUBNET} ct state established,related counter accept']
    ingress += [f'{i} counter drop']
    forward += [f'{i} counter drop', f'{o} counter drop']
    if mode == 'blocked':
        output += [f'{o} counter drop']
    return dict(zip(CHAINS, (ingress, forward, output)))


def nft_program(owner, mode, create=False):
    lines = []
    if create:
        # Values are validated internally; no user-provided nft expressions.
        if not re.fullmatch(r'AAG-Hotspot-Control session=[0-9a-f-]{36}', owner.marker):
            raise ValueError('Invalid ownership marker')
        lines.append(f'add table inet {TABLE} {{ comment "{owner.marker}"; }}')
        for chain, hook in zip(CHAINS, ('input', 'forward', 'output')):
            lines.append(f'add chain inet {TABLE} {chain} {{ type filter hook {hook} priority -10; policy accept; }}')
    else:
        lines += [f'flush chain inet {TABLE} {c}' for c in CHAINS]
    for chain, entries in rules(owner.vif, mode).items():
        lines += [f'add rule inet {TABLE} {chain} {entry}' for entry in entries]
    return '\n'.join(lines) + '\n'


def table_digest(text):
    """Ignore rule handles/counters only; retain table identity and expressions."""
    text = re.sub(r'counter packets \d+ bytes \d+', 'counter packets LIVE bytes LIVE', text)
    text = re.sub(r' # handle \d+', '', text)
    return hashlib.sha256(text.encode()).hexdigest()


def validate_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 63 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError('Use 12–63 printable ASCII characters for the Wi-Fi password')
    return value
