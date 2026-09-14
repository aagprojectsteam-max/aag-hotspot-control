"""Administrator endpoint; exact actions, fixed paths, secret-safe errors."""
import json
import os
import signal
import sys
import time
from . import ownership as rb
from .backend import Backend
from .controller import Controller
from .state import Store, LOCK_WAIT, RECOVERY_LOCK_WAIT

ACTIONS = ('internet', 'local', 'off', 'configure', 'doctor')


def deadline(signum, frame):
    raise rb.OperationError('OPERATION_INTERRUPTED: recovery required')


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0 or len(args) != 1 or args[0] not in ACTIONS:
        print(json.dumps({'ok': False, 'error': 'INVALID_PRIVILEGED_REQUEST'}))
        return 2
    action = args[0]
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, deadline)
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)
    try:
        store, backend = Store(), Backend()
        if action == 'doctor':
            # Read-only, does not construct runtime state or start the supervisor.
            checks = {'firewall_readable': bool(backend.json_run(['/usr/sbin/nft', '-j', 'list', 'tables'])),
                      'wifi_idle': backend.wifi_idle(), 'public_route': backend.route_source(),
                      'configured': store.configured()}
            with store.locked(create=False) as present:
                data = store.load() if present else None
                if data:
                    controller = Controller(backend, store)
                    if data['phase'] == 'active':
                        backend.healthy(controller.owner(data), data['mode'], data['guard_digest'])
                    checks['phase'] = data['phase']
                else: checks['phase'] = 'off'
            result = {'ok': True, 'checks': checks, 'physical_client_validation': 'NOT_TESTED'}
        else:
            with store.locked(create=action != 'off',
                              timeout=RECOVERY_LOCK_WAIT if action == 'off' else LOCK_WAIT) as present:
                controller = Controller(backend, store)
                if not present:
                    result = {'ok': True, 'status': controller.status()}
                elif action == 'configure':
                    if store.load(): raise rb.OperationError('Turn the hotspot off before changing its password')
                    password = sys.stdin.buffer.read(65)
                    try: password = password.decode('ascii').removesuffix('\n')
                    except UnicodeDecodeError: raise ValueError('Password must use printable ASCII') from None
                    store.configure(password)
                    password = None
                    value = controller.status()
                    store.publish(value)
                    result = {'ok': True, 'status': value}
                else:
                    value = controller.stop() if action == 'off' else controller.start(action)
                    result = {'ok': True, 'status': value}
        print(json.dumps(result))
        return 0
    except (rb.SafetyError, rb.OperationError, ValueError, FileNotFoundError) as exc:
        # These exceptions have controlled text only; subprocess/D-Bus bodies are never emitted.
        text = 'CONFIGURATION_REQUIRED' if isinstance(exc, FileNotFoundError) else str(exc)
        print(json.dumps({'ok': False, 'error': text}))
        return 1
    except Exception:
        print(json.dumps({'ok': False, 'error': 'INTERNAL_ERROR_RECOVERY_REQUIRED'}))
        return 1
    finally:
        signal.alarm(0)


def watch():
    if os.geteuid() != 0: return 2
    os.umask(0o077)
    store, backend = Store(), Backend()
    while True:
        try:
            # Background health checks never queue ahead of foreground recovery.
            # A busy check is skipped; the existing 2s cadence gives waiting OFF
            # (50ms lock polling) a chance before the next supervisor acquisition.
            with store.locked(create=False, timeout=0) as present:
                if not present or not Controller(backend, store).tick(): return 0
        except rb.OperationError as exc:
            if not str(exc).startswith('BUSY:'):
                print('AAG recovery incomplete; owned state retained for off/review.', flush=True)
        except Exception:
            print('AAG ownership/state requires review; unrelated state preserved.', flush=True)
        time.sleep(2)
