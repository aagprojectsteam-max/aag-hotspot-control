"""Fixed local command adapter. No shell, arbitrary uplinks or modem writes."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time
from . import ownership as rb
from .policy import ADDRESS, SUBNET, SSID, CELL_UUID, STA, PHY, SERVICE, nft_program, table_digest


class Backend(rb.Backend):
    READINESS_TIMEOUT = 10.0
    READINESS_POLL = 0.25

    def _readiness_read(self, argv, deadline):
        """Read-only probes share the wait's deadline, including hung nmcli calls."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        try:
            r = subprocess.run(argv, capture_output=True, text=True, env=rb.ENV,
                               timeout=min(2.0, remaining))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise TimeoutError() from None
            raise rb.OperationError('NM_READINESS_UNAVAILABLE: nmcli inspection timed out') from None
        except OSError:
            raise rb.OperationError('NM_READINESS_UNAVAILABLE: cannot inspect NetworkManager') from None
        if r.returncode:
            raise rb.OperationError(f'NM_READINESS_UNAVAILABLE: nmcli inspection failed (exit {r.returncode})')
        return r.stdout.strip()

    def wait_device_ready(self, owner):
        """Wait after radio-on for this owned Wi-Fi device, never for its P2P sibling.

        NM state 30 (DISCONNECTED) means idle and activation-capable. States
        0/10/20 may occur during discovery/supplicant startup. No activation is
        retried here; failure propagates to the controller's existing rollback.
        """
        if not re.fullmatch(r'aaghp[0-9a-f]{8}', owner.vif):
            raise rb.SafetyError('Readiness requires the exact production-owned interface')
        deadline = time.monotonic() + self.READINESS_TIMEOUT
        last = 'device=not-observed'
        try:
            while True:
                general = self._readiness_read(['/usr/bin/nmcli', '-g', 'RUNNING,WIFI-HW,WIFI',
                                               'general', 'status'], deadline).split(':')
                if len(general) != 3 or general[0] != 'running':
                    raise rb.OperationError('NM_READINESS_UNAVAILABLE: NetworkManager is not running')
                if general[1] != 'enabled' or general[2] != 'enabled':
                    raise rb.OperationError('NM_DEVICE_RFKILL_BLOCKED: Wi-Fi hardware/software radio is not enabled')
                devices = self._readiness_read(['/usr/bin/nmcli', '-g', 'DEVICE', 'device', 'status'], deadline).splitlines()
                ready = False
                last = 'device=not-discovered'
                if owner.vif in devices:
                    fields = 'GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.REASON,GENERAL.NM-MANAGED,GENERAL.AUTOCONNECT'
                    values = self._readiness_read(['/usr/bin/nmcli', '-g', fields, 'device', 'show', owner.vif], deadline).splitlines()
                    if len(values) != 6 or values[:2] != [owner.vif, 'wifi'] or any(x not in ('yes', 'no') for x in values[4:]):
                        raise rb.OperationError('NM_DEVICE_READINESS_INVALID: unexpected device identity/properties')
                    # Keep only numeric codes in diagnostics; never emit raw NM output.
                    codes = [re.fullmatch(r'(\d{1,3})(?: \([^\n]*\))?', x) for x in values[2:4]]
                    if not all(codes):
                        raise rb.OperationError('NM_DEVICE_READINESS_INVALID: unknown state/reason format')
                    state, reason = (int(x[1]) for x in codes)
                    last = f'device={owner.vif} state={state} reason={reason} managed={values[4]}'
                    if values[5] != 'no':
                        raise rb.SafetyError('Owned AP device autoconnect changed during readiness wait')
                    if state not in (0, 10, 20, 30):
                        raise rb.OperationError('NM_DEVICE_READINESS_CONFLICT: ' + last)
                    ready = state == 30 and values[4] == 'yes'
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if ready:
                    return
                # Rate-limited, condition-based polling, not a fixed startup delay.
                time.sleep(min(self.READINESS_POLL, remaining))
        except TimeoutError:
            raise rb.OperationError(f'NM_DEVICE_READINESS_TIMEOUT: {self.READINESS_TIMEOUT:g}s; {last}') from None

    def nft(self, program):
        try:
            r = subprocess.run(['/usr/sbin/nft', '-f', '-'], input=program, text=True,
                               capture_output=True, timeout=15, env=rb.ENV)
        except (OSError, subprocess.TimeoutExpired):
            raise rb.OperationError('Firewall transaction unavailable/timed out') from None
        if r.returncode:
            raise rb.OperationError('Atomic AAG firewall transaction failed')

    def guard(self, owner, mode, create=False):
        existing = self.table(owner)
        if create and existing is not None:
            raise rb.SafetyError('AAG table name is occupied; refusing adoption')
        if not create:
            if existing is None or existing.get('comment') != owner.marker or existing.get('handle') != owner.table_handle:
                raise rb.SafetyError('Guard identity changed; refusing replacement')
            self.verify_chain_layout(owner)
        self.nft(nft_program(owner, mode, create))
        return self.table(owner)['handle'], self.guard_digest(owner)

    def verify_chain_layout(self, owner):
        data = self.json_run(['/usr/sbin/nft', '-j', 'list', 'table', 'inet', owner.table])
        chains = [x['chain'] for x in data['nftables'] if 'chain' in x]
        expected = {f'{hook}_guard': hook for hook in ('input', 'forward', 'output')}
        if len(chains) != 3 or {x['name'] for x in chains} != set(expected):
            raise rb.SafetyError('Unexpected chains in AAG table')
        for x in chains:
            if (x.get('hook') != expected[x['name']] or x.get('type') != 'filter'
                    or x.get('prio') != -10 or x.get('policy') != 'accept'):
                raise rb.SafetyError('AAG guard hooks changed')

    def guard_digest(self, owner):
        return table_digest(self.run(['/usr/sbin/nft', '-a', 'list', 'table', 'inet', owner.table]))

    def route_source(self):
        data = self.json_run(['/usr/sbin/ip', '-j', '-4', 'route', 'get', '1.1.1.1'])
        return data[0].get('dev') if data else None

    def cellular(self):
        defaults = self.json_run(['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'default'])
        if (self.active().get(CELL_UUID) != ['wwan0mbim0'] or not defaults
                or any(x.get('dev') != 'wwan0' for x in defaults) or self.route_source() != 'wwan0'):
            raise rb.OperationError('CELLULAR_REQUIRED: the validated default uplink must be wwan0')

    def preflight(self, mode):
        from .binding import READY
        if not READY:
            raise rb.OperationError('HOST_BINDING_REQUIRED: install the public package on this host first')
        if not self.wifi_idle():
            raise rb.OperationError('WIFI_STA_UNVALIDATED: preserve current Wi-Fi; STA + AP is not enabled')
        if self.run(['/usr/bin/nmcli', '-g', 'WIFI-HW', 'general', 'status']) != 'enabled':
            raise rb.OperationError('Wi-Fi hardware radio is blocked')
        if self.run(['/usr/sbin/sysctl', '-n', 'net.ipv4.ip_forward']) != '1':
            raise rb.OperationError('IPv4 forwarding baseline must already be enabled; global settings will not be changed')
        config = self.run(['/usr/sbin/NetworkManager', '--print-config'])
        if not re.search(r'^firewall-backend=iptables$', config, re.M):
            raise rb.OperationError('NM firewall backend differs from the validated iptables path')
        info = self.run(['/usr/sbin/iw', 'phy', 'phy' + str(PHY), 'info'])
        channel = re.search(r'^\s*\* 2437(?:\.0)? MHz \[6\].*$', info, re.M)
        if not channel or any(x in channel[0].lower() for x in ('disabled', 'no ir', 'radar')):
            raise rb.OperationError('Channel 6 is not currently allowed for AP initiation')
        if mode == 'internet': self.cellular()
        for route in self.json_run(['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'table', 'all']):
            dst = route.get('dst', 'default')
            if dst != 'default' and ipaddress.ip_network(dst, strict=False).overlaps(ipaddress.ip_network(SUBNET)):
                raise rb.OperationError('AP subnet overlaps an existing route')
        if any(x.get('table', {}).get('family') == 'inet' and x.get('table', {}).get('name') == 'aag_hotspot'
               for x in self.json_run(['/usr/sbin/nft', '-j', 'list', 'tables'])['nftables']):
            raise rb.SafetyError('Existing aag_hotspot table without a registered session; inspect manually')
        if any(x['ifname'].startswith('aaghp') for x in self.links()):
            raise rb.SafetyError('Possible orphan AAG interface; never adopt or delete by prefix')

    def arm_watch(self):
        # Restart avoids racing a previous completed session's exiting watcher.
        self.run(['/usr/bin/systemctl', 'restart', SERVICE])
        if self.run(['/usr/bin/systemctl', 'is-active', SERVICE]) != 'active':
            raise rb.OperationError('Recovery supervisor did not start')

    def planned_absent(self, owner):
        import os
        if self.profile(owner) or self.interface(owner) or self.table(owner):
            raise rb.SafetyError('Planned session identity is occupied')
        for path in (Path('/run') / ('nm-dnsmasq-' + owner.vif + '.pid'),
                     Path('/var/lib/NetworkManager') / ('dnsmasq-' + owner.vif + '.leases')):
            if os.path.lexists(path): raise rb.SafetyError('Planned NM runtime file already exists')

    def create_interface(self, owner):
        self.run(['/usr/sbin/iw', 'phy', 'phy' + str(PHY), 'interface', 'add', owner.vif, 'type', '__ap', 'addr', owner.mac])
        for _ in range(20):
            devices = self.run(['/usr/bin/nmcli', '-g', 'DEVICE', 'device', 'status']).splitlines()
            if owner.vif in devices:
                self.run(['/usr/bin/nmcli', 'device', 'set', owner.vif, 'autoconnect', 'no'])
                return self.interface(owner)['ifindex']
            time.sleep(0.25)
        raise rb.OperationError('NM did not discover the owned interface')

    def add_profile(self, owner, password):
        from gi.repository import Gio, GLib
        v = GLib.Variant
        settings = {
            'connection': {'id': v('s', owner.profile_name), 'uuid': v('s', owner.profile_uuid),
                           'type': v('s', '802-11-wireless'), 'interface-name': v('s', owner.vif),
                           'autoconnect': v('b', False)},
            '802-11-wireless': {'ssid': v('ay', list(SSID.encode())), 'mode': v('s', 'ap'),
                               'band': v('s', 'bg'), 'channel': v('u', 6),
                               'assigned-mac-address': v('s', owner.mac), 'ap-isolation': v('i', 0)},
            '802-11-wireless-security': {'key-mgmt': v('s', 'wpa-psk'), 'proto': v('as', ['rsn']),
                                        'pairwise': v('as', ['ccmp']), 'group': v('as', ['ccmp']), 'psk': v('s', password)},
            'ipv4': {'method': v('s', 'shared'), 'never-default': v('b', True), 'may-fail': v('b', False),
                     'address-data': v('aa{sv}', [{'address': v('s', ADDRESS), 'prefix': v('u', 24)}])},
            'ipv6': {'method': v('s', 'disabled')},
        }
        try:
            Gio.bus_get_sync(Gio.BusType.SYSTEM, None).call_sync(
                'org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager/Settings',
                'org.freedesktop.NetworkManager.Settings', 'AddConnection2',
                v('(a{sa{sv}}ua{sv})', (settings, 34, {})), GLib.VariantType.new('(oa{sv})'),
                Gio.DBusCallFlags.NONE, 15000, None)
        except Exception:
            raise rb.OperationError('Could not create transient NM profile; secret details suppressed') from None

    def activate(self, owner):
        self.run(['/usr/bin/nmcli', '--wait', '20', 'connection', 'up', 'uuid', owner.profile_uuid, 'ifname', owner.vif])

    def healthy(self, owner, mode, digest):
        rb.Rollback(owner, self, emit=lambda _: None).inspect()
        if self.active().get(owner.profile_uuid) != [owner.vif]:
            raise rb.OperationError('Owned AP is no longer active')
        iface = self.interface(owner)
        if not iface or iface['mode'] != 'AP':
            raise rb.OperationError('Kernel AP mode is not confirmed')
        info = self.run(['/usr/sbin/iw', 'dev', owner.vif, 'info'])
        if '\tssid AAG-Hotspot\n' not in info or 'channel 6 (2437 MHz), width: 20 MHz' not in info:
            raise rb.OperationError('SSID/channel/width differs from the validated path')
        addresses = self.json_run(['/usr/sbin/ip', '-j', 'address', 'show', 'dev', owner.vif])[0]['addr_info']
        if not any(x.get('local') == ADDRESS and x.get('prefixlen') == 24 for x in addresses):
            raise rb.OperationError('AP address is absent')
        if any(x.get('family') == 'inet6' for x in addresses):
            raise rb.OperationError('Unexpected AP IPv6 address')
        self.verify_chain_layout(owner)
        if self.guard_digest(owner) != digest:
            raise rb.SafetyError('AAG guard changed unexpectedly')
        self.sharing_infrastructure(owner)
        if self.run(['/usr/sbin/iw', 'dev', STA, 'link']) != 'Not connected.':
            raise rb.OperationError('An unvalidated Wi-Fi STA connection appeared')
        if mode == 'internet': self.cellular()

    def sharing_infrastructure(self, owner):
        saved = self.run(['/usr/sbin/iptables-save'])
        required = (':nm-sh-in-' + owner.vif + ' ', ':nm-sh-fw-' + owner.vif + ' ',
                    '-A INPUT -i ' + owner.vif + ' ',
                    '-A FORWARD -m comment --comment nm-shared-' + owner.vif + ' ',
                    '-A POSTROUTING -s 10.77.0.0/24 ! -d 10.77.0.0/24 -m comment --comment nm-shared-' + owner.vif + ' -j MASQUERADE')
        if not all(x in saved for x in required):
            raise rb.OperationError('Required NM DHCP/DNS/forward/NAT rules are incomplete')
        # Read exact NM process identity; no broad pgrep/kill or PID-file adoption.
        pidfile = Path('/run') / ('nm-dnsmasq-' + owner.vif + '.pid')
        import os, stat
        fd = os.open(pidfile, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > 32: raise rb.SafetyError('Invalid NM dnsmasq PID file')
            pid = f.read().strip()
        if not re.fullmatch(r'[1-9][0-9]{0,9}', pid): raise rb.SafetyError('Invalid NM dnsmasq PID')
        args = (Path('/proc') / pid / 'cmdline').read_bytes().split(b'\0')
        expected = [b'/usr/sbin/dnsmasq', b'--listen-address=10.77.0.1',
                    ('--pid-file=' + str(pidfile)).encode(),
                    ('--dhcp-leasefile=/var/lib/NetworkManager/dnsmasq-' + owner.vif + '.leases').encode()]
        if not all(x in args for x in expected): raise rb.SafetyError('NM DNS/DHCP process identity changed')
        sockets = self.run(['/usr/bin/ss', '-lntup'])
        lines = [x for x in sockets.splitlines() if 'pid=' + pid + ',' in x]
        if not (any(x.startswith('udp ') and '10.77.0.1:53 ' in x for x in lines)
                and any(x.startswith('tcp ') and '10.77.0.1:53 ' in x for x in lines)
                and any(x.startswith('udp ') and ':67 ' in x for x in lines)):
            raise rb.OperationError('NM DHCP/DNS sockets are not ready')

    def clients(self, owner):
        return self.client_snapshot(owner)['clients']

    def client_snapshot(self, owner):
        from .clients import Probe, snapshot
        return snapshot(Probe(), owner)

    def remove_lease(self, owner):
        # Owned derived path; only after AP/profile/NM firewall cleanup.
        path = Path('/var/lib/NetworkManager') / ('dnsmasq-' + owner.vif + '.leases')
        try: st = path.lstat()
        except FileNotFoundError: return
        import stat
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise rb.SafetyError('Unexpected lease-file identity')
        path.unlink()
