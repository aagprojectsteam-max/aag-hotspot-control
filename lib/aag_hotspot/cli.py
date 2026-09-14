import argparse
import getpass
import json
import sys
from . import __version__
from . import client
from .policy import SSID, SUBNET


def main(argv=None):
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description='AAG Hotspot — cellular-only NetworkManager AP controller')
    parser.add_argument('command', choices=('internet', 'local', 'off', 'status', 'doctor', 'configure'))
    parser.add_argument('--json', action='store_true', help='Machine-readable output; never includes passwords')
    parser.add_argument('--dry-run', action='store_true', help='Describe requested action; do not invoke privilege helper')
    parser.add_argument('--privileged', action='store_true', help='Administrator read-only doctor inspection')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    if args.privileged and args.command != 'doctor': parser.error('--privileged is only valid with doctor')
    if args.dry_run:
        result = {'ok': True, 'dry_run': True, 'action': args.command, 'ssid': SSID, 'subnet': SUBNET,
                  'uplink_policy': 'wwan0 only; Wi-Fi STA+AP disabled',
                  'network_changes': False, 'physical_client_validation': 'NOT_TESTED'}
    elif args.command == 'status': result = client.status()
    elif args.command == 'doctor':
        result = client.request('doctor') if args.privileged else client.doctor()
    elif args.command == 'configure':
        if not sys.stdin.isatty(): parser.error('configure requires a terminal; passwords are never command-line arguments')
        password = getpass.getpass('Wi-Fi password (12–63 printable ASCII characters): ')
        if password != getpass.getpass('Repeat password: '): parser.error('Passwords do not match')
        try: result = client.request('configure', password)
        except ValueError as exc: parser.error(str(exc))
        finally: password = None
    else: result = client.request(args.command)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        for k, v in result.items():
            print(k.upper() + '=' + (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)))
        if args.command == 'status':
            for index, row in enumerate(result.get('client_details', []), 1):
                for key in ('mac', 'ipv4', 'hostname', 'signal_dbm', 'connected_seconds'):
                    print('CLIENT_' + str(index) + '_' + key.upper() + '=' + str(row.get(key) if row.get(key) is not None else 'UNKNOWN'))
    health = result.get('health', result.get('status', {}).get('health'))
    return 1 if result.get('ok') is False or health in ('ERROR', 'UNKNOWN', 'NOT_INSTALLED') else 0
