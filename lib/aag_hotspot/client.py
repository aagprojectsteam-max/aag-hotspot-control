"""Unprivileged public inspection and the sole CLI/GUI action transport."""
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from .policy import SSID, validate_password
from .clients import MAX_PUBLIC_BYTES, expire

HELPER = '/usr/libexec/aag-hotspot-helper'
PUBLIC = Path('/run/aag-hotspot/status.json')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'NM_CLI_COLOR': 'never'}


def probe(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=8, env=ENV)
        return {'ok': r.returncode == 0, 'stdout': r.stdout.strip() if r.returncode == 0 else ''}
    except (OSError, subprocess.TimeoutExpired):
        return {'ok': False, 'stdout': ''}


def status():
    installed = Path(HELPER).is_file()
    value = {'schema': 1, 'mode': 'off', 'phase': 'off', 'ssid': SSID, 'ipv4': None,
             'interface': None, 'clients': 0, 'configured': Path('/var/lib/aag-hotspot/credentials.json').is_file(), 'uplink': None,
             'health': 'OK', 'error': None, 'installed': installed,
             'wifi_uplink': 'UNVALIDATED_DISABLED', 'physical_client_validation': 'NOT_TESTED'}
    try:
        parent = PUBLIC.parent.lstat()
        if parent.st_uid != 0 or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o022:
            raise ValueError('Untrusted state parent')
        fd = os.open(PUBLIC, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022 or st.st_size > MAX_PUBLIC_BYTES:
                raise ValueError('Untrusted public state')
            data = json.load(f)
        if (data.get('schema') != 1 or data.get('mode') not in ('off', 'local', 'internet')
                or data.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
            raise ValueError('Invalid/stale status')
        value.update(data)
        if data['phase'] != 'off' and time.monotonic() - data.get('updated_monotonic', 0) > 60:
            value.update(health='UNKNOWN', error='STALE_STATUS')
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, AttributeError):
        value.update(mode='unknown', phase='unknown', health='UNKNOWN', error='STATE_UNREADABLE')
    route = probe(['/usr/sbin/ip', '-j', '-4', 'route', 'get', '1.1.1.1'])
    try:
        routes = json.loads(route['stdout']) if route['ok'] else []
        dev = routes[0].get('dev') if isinstance(routes, list) and routes and isinstance(routes[0], dict) else None
        value['uplink'] = dev if isinstance(dev, str) else None
    except ValueError: value['uplink'] = None
    value['installed'] = installed
    if not installed: value.update(health='NOT_INSTALLED', error='INSTALLATION_REQUIRED')
    return expire(value)


def doctor():
    import shutil
    checks = {name: shutil.which(name, path=ENV['PATH']) is not None
              for name in ('nmcli', 'iw', 'ip', 'nft', 'iptables-save', 'dnsmasq', 'pkexec', 'systemctl')}
    current = status()
    checks['helper_installed'] = current['installed']
    checks['password_configured'] = current['configured']
    checks['cellular_public_route'] = current['uplink'] == 'wwan0'
    return {'status': current, 'checks': checks, 'protected_firewall_inspection': 'REQUIRES_PRIVILEGED_DOCTOR',
            'physical_client_validation': 'NOT_TESTED', 'wifi_uplink': 'UNVALIDATED_DISABLED'}


def request(action, password=None):
    if action not in ('internet', 'local', 'off', 'configure', 'doctor'):
        raise ValueError('Unsupported action')
    if action == 'configure': validate_password(password)
    elif password is not None: raise ValueError('Unexpected password input')
    if not Path(HELPER).is_file():
        return {'ok': False, 'error': 'INSTALLATION_REQUIRED'}
    # No shell or caller-provided helper path; secret only over stdin after pkexec.
    try:
        r = subprocess.run(['/usr/bin/pkexec', HELPER, action],
                           input=password + '\n' if password is not None else '',
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'TIMEOUT_RECOVERY_PENDING'}
    except OSError:
        return {'ok': False, 'error': 'HELPER_UNAVAILABLE'}
    if r.returncode in (126, 127):
        return {'ok': False, 'error': 'AUTHENTICATION_CANCELLED_OR_DENIED'}
    try:
        value = json.loads(r.stdout)
        if not isinstance(value, dict) or type(value.get('ok')) is not bool:
            raise ValueError()
        if value['ok'] and r.returncode != 0:
            raise ValueError()
        if any(key in value and not isinstance(value[key], dict) for key in ('status', 'checks')):
            raise ValueError()
        if value.get('error') is not None and not isinstance(value['error'], str):
            raise ValueError()
        return value
    except ValueError:
        return {'ok': False, 'error': 'HELPER_PROTOCOL_ERROR'}
