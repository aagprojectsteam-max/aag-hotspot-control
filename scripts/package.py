#!/usr/bin/python3
"""Scoped installer/uninstaller. Staging never invokes system/network commands."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
sys.dont_write_bytecode = True

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = Path('usr/lib/aag-hotspot/install-manifest.json')
BINDING = Path('usr/lib/aag-hotspot/host.json')
SYSTEM_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
              'SYSTEMD_PAGER': 'cat', 'SYSTEMD_COLORS': '0'}


def source_map():
    files = {Path('usr/lib/aag-hotspot/aag_hotspot') / p.name: p
             for p in (PROJECT / 'lib/aag_hotspot').glob('*.py')}
    files.update({Path('usr/lib/aag-hotspot') / name: PROJECT / 'lib' / name
                  for name in ('entry.py', 'watch.py')})
    files.update({Path('usr/bin') / name: PROJECT / 'bin' / name
                  for name in ('aag-hotspot', 'aag-hotspot-gui')})
    files.update({Path('usr/libexec/aag-hotspot-helper'): PROJECT / 'bin/aag-hotspot-helper',
                  Path('usr/share/applications/org.aag.Hotspot.desktop'): PROJECT / 'desktop/org.aag.Hotspot.desktop',
                  Path('usr/share/icons/hicolor/scalable/apps/aag-hotspot.svg'): PROJECT / 'desktop/aag-hotspot.svg',
                  Path('usr/share/polkit-1/actions/org.aag.hotspot.policy'): PROJECT / 'polkit/org.aag.hotspot.policy',
                  Path('usr/lib/systemd/system/aag-hotspot-watch.service'): PROJECT / 'systemd/aag-hotspot-watch.service'})
    for icon in (PROJECT / 'desktop/icons/hicolor/scalable/status').glob('aag-hotspot-*-symbolic.svg'):
        files[Path('usr/share/icons/hicolor/scalable/status') / icon.name] = icon
    for name in ('README.md', 'LICENSE', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md', 'THIRD_PARTY.md'):
        files[Path('usr/share/doc/aag-hotspot') / name] = PROJECT / name
    for path in (PROJECT / 'docs').rglob('*'):
        if path.is_file() and path.suffix in ('.md', '.png'):
            files[Path('usr/share/doc/aag-hotspot/docs') / path.relative_to(PROJECT / 'docs')] = path
    files[Path('usr/share/doc/aag-hotspot/configuration.md')] = PROJECT / 'config/README.md'
    return files


def checked_path(root, relative):
    if relative.is_absolute() or '..' in relative.parts:
        raise RuntimeError('Unsafe package path')
    p = root
    for part in relative.parts:
        p = p / part
        if p.is_symlink(): raise RuntimeError('Symlink in installation path: ' + str(relative))
        if root == Path('/') and p.exists():
            st = p.stat()
            if st.st_uid != 0 or st.st_mode & 0o022:
                raise RuntimeError('Untrusted host installation path: ' + str(relative))
    return p


def digest(path):
    if not stat.S_ISREG(path.lstat().st_mode): raise RuntimeError('Non-regular package file')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_file(path, data, mode):
    """Replace one owned file without exposing partial content."""
    import tempfile
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.aag-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            os.fchmod(f.fileno(), mode)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def installed_receipt(root):
    path = checked_path(root, MANIFEST)
    if not path.exists(): return None
    if path.stat().st_size > 65536: raise RuntimeError('Invalid package receipt')
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or not isinstance(data.get('files'), dict):
        raise RuntimeError('Invalid package receipt')
    # Receipt cannot expand deletion scope beyond the package's fixed paths.
    allowed = {str(p) for p in source_map()} | {str(BINDING)}
    if not set(data['files']).issubset(allowed): raise RuntimeError('Receipt contains unrelated paths')
    return data


def inactive(root, system):
    if os.path.lexists(root / 'run/aag-hotspot/private/session.json'):
        raise RuntimeError('AAG session exists: run aag-hotspot off before installing/uninstalling')
    if system:
        r = subprocess.run(['/usr/bin/systemctl', 'is-active', 'aag-hotspot-watch.service'],
                           capture_output=True, text=True, timeout=15, env=SYSTEM_ENV)
        if r.stdout.strip() in ('active', 'activating', 'deactivating', 'reloading'):
            raise RuntimeError('AAG recovery supervisor still active; finish off/recovery first')


def refresh(system):
    if system:
        subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True, timeout=30, env=SYSTEM_ENV)
        desktop_tool = shutil.which('update-desktop-database', path=SYSTEM_ENV['PATH'])
        if desktop_tool:
            subprocess.run([desktop_tool, '/usr/share/applications'], check=True, timeout=30, env=SYSTEM_ENV)


def install(root, system, wifi_interface=None, rebind=False):
    inactive(root, system)
    files = source_map()
    receipt = installed_receipt(root)
    binding_data = None
    if system:
        sys.path.insert(0, str(PROJECT / 'scripts'))
        import host_environment
        # Check compatibility on every update; never write global settings.
        discovered = host_environment.detect(wifi_interface)
        if receipt and str(BINDING) in receipt['files'] and not rebind:
            binding_data = checked_path(root, BINDING).read_bytes()
        else:
            binding_data = (json.dumps(discovered, sort_keys=True) + '\n').encode()
    old = receipt['files'] if receipt else {}
    binding_path = checked_path(root, BINDING)
    if binding_path.exists() and str(BINDING) not in old:
        raise RuntimeError('Unowned host binding exists; refusing overwrite')
    for relative in files:
        path = checked_path(root, relative)
        if path.exists() and (str(relative) not in old or digest(path) != old[str(relative)]['sha256']):
            raise RuntimeError('Refusing to overwrite unowned/modified file: ' + str(relative))
    for rel, meta in old.items():
        p = checked_path(root, Path(rel))
        if not p.exists() or digest(p) != meta['sha256'] or stat.S_IMODE(p.stat().st_mode) != meta['mode']:
            raise RuntimeError('Existing installation has changed; preserve for review')
    # Read every source before replacing any installed file. A missing source
    # cannot leave a half-updated installation.
    payloads = {relative: source.read_bytes() for relative, source in files.items()}
    if binding_data is not None:
        payloads[BINDING] = binding_data
    elif receipt and str(BINDING) in receipt['files']:
        payloads[BINDING] = checked_path(root, BINDING).read_bytes()
    record = {'schema': 1, 'version': '0.2.1', 'files': {}}
    pending = {}
    for relative, data in payloads.items():
        path = checked_path(root, relative)
        mode = 0o755 if relative.parts[1] in ('bin', 'libexec') else 0o644
        record['files'][str(relative)] = {'sha256': hashlib.sha256(data).hexdigest(), 'mode': mode}
        if not path.exists() or path.read_bytes() != data or stat.S_IMODE(path.stat().st_mode) != mode:
            pending[path] = (data, mode)
    manifest = checked_path(root, MANIFEST)
    data = (json.dumps(record, indent=2) + '\n').encode()
    if not manifest.exists() or manifest.read_bytes() != data:
        pending[manifest] = (data, 0o644)
    previous = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
                for path in pending}
    changed = []
    try:
        for path, (data, mode) in pending.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            checked_path(root, path.relative_to(root))
            atomic_file(path, data, mode)
            changed.append(path)
        if pending: refresh(system)
    except Exception:
        # Ordinary copy/refresh errors restore prior files. Power loss/SIGKILL
        # can still require receipt review; never guess ownership on retry.
        for path in reversed(changed):
            if previous[path] is None: path.unlink()
            else: atomic_file(path, *previous[path])
        raise
    return {'installed_files': len(files), 'changed_files': len(pending), 'activation': False,
            'autostart': False, 'staging': not system}


def uninstall(root, system, purge=False, dry_run=False):
    inactive(root, system)
    receipt = installed_receipt(root)
    if receipt is None: return {'removed_files': 0, 'status': 'NOT_INSTALLED'}
    for relative, meta in receipt['files'].items():
        p = checked_path(root, Path(relative))
        if not p.exists() or digest(p) != meta['sha256'] or stat.S_IMODE(p.stat().st_mode) != meta['mode']:
            raise RuntimeError('Refusing to delete changed/missing application file: ' + relative)
    runtime = checked_path(root, Path('run/aag-hotspot'))
    # Only known, inactive cache/empty lock-directory state may be retired.
    if runtime.exists():
        if not {x.name for x in runtime.iterdir()}.issubset({'private', 'status.json'}):
            raise RuntimeError('Unknown AAG runtime files require review')
        private = checked_path(root, Path('run/aag-hotspot/private'))
        if private.exists() and (not private.is_dir() or list(private.iterdir())):
            raise RuntimeError('Private runtime state is not empty')
        public = checked_path(root, Path('run/aag-hotspot/status.json'))
        if public.exists():
            if not public.is_file() or public.stat().st_size > 8192:
                raise RuntimeError('Invalid inactive status cache')
            status = json.loads(public.read_text())
            if status.get('schema') != 1 or status.get('phase') != 'off' or status.get('mode') != 'off':
                raise RuntimeError('Runtime status is not confirmed off')
    credential = checked_path(root, Path('var/lib/aag-hotspot/credentials.json')) if purge else None
    if credential is not None and credential.exists():
        if not stat.S_ISREG(credential.lstat().st_mode) or credential.stat().st_nlink != 1:
            raise RuntimeError('Unsafe credential file; preserved')
    if dry_run:
        return {'dry_run': True, 'validated_files': len(receipt['files']),
                'would_remove': sorted(receipt['files']) + [str(MANIFEST)],
                'credentials_preserved': not purge, 'network_changes': False}
    for relative in receipt['files']: checked_path(root, Path(relative)).unlink()
    checked_path(root, MANIFEST).unlink()
    for directory in ('usr/lib/aag-hotspot/aag_hotspot', 'usr/lib/aag-hotspot',
                      'usr/share/doc/aag-hotspot/docs/screenshots', 'usr/share/doc/aag-hotspot/docs',
                      'usr/share/doc/aag-hotspot'):
        p = checked_path(root, Path(directory))
        try: p.rmdir()
        except OSError: pass  # Never recursive deletion of unexpected files.
    if runtime.exists():
        (runtime / 'status.json').unlink(missing_ok=True)
        if (runtime / 'private').exists(): (runtime / 'private').rmdir()
        runtime.rmdir()
    if purge:
        p = checked_path(root, Path('var/lib/aag-hotspot/credentials.json'))
        if p.exists():
            if not stat.S_ISREG(p.lstat().st_mode) or p.stat().st_nlink != 1:
                raise RuntimeError('Unsafe credential file; preserved')
            p.unlink()
        parent = root / 'var/lib/aag-hotspot'
        if parent.exists():
            try: parent.rmdir()
            except OSError: pass
    refresh(system)
    return {'removed_files': len(receipt['files']), 'credentials_preserved': not purge, 'network_changes': False}


def stop_for_uninstall():
    """Use the installed, receipt-verified OFF path before taking the package lock."""
    receipt = installed_receipt(Path('/'))
    if receipt is None: return
    for relative, meta in receipt['files'].items():
        path = checked_path(Path('/'), Path(relative))
        if digest(path) != meta['sha256'] or stat.S_IMODE(path.stat().st_mode) != meta['mode']:
            raise RuntimeError('Modified installed file; preserve installation and inspect locally')
    try:
        result = subprocess.run(['/usr/libexec/aag-hotspot-helper', 'off'],
                                capture_output=True, timeout=90, env=SYSTEM_ENV)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('AAG OFF did not complete; installation retained for recovery') from None
    if result.returncode:
        raise RuntimeError('AAG OFF failed; installation retained for recovery')
    import time
    end = time.monotonic() + 15
    while True:
        state = subprocess.run(['/usr/bin/systemctl', 'is-active', 'aag-hotspot-watch.service'],
                               capture_output=True, text=True, timeout=3, env=SYSTEM_ENV)
        if state.stdout.strip() in ('inactive', 'failed', 'unknown'): return
        if time.monotonic() >= end: raise RuntimeError('AAG supervisor still running; no files removed')
        time.sleep(.25)


def main():
    os.umask(0o022)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('install', 'uninstall'))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--root', type=Path, help='Staging tree only, never /')
    group.add_argument('--system', action='store_true', help='Explicit installation on this host; requires administrator')
    p.add_argument('--wifi-interface', help='Bind one existing Wi-Fi interface on initial installation')
    p.add_argument('--rebind', action='store_true', help='Explicitly refresh nonsecret local bindings while OFF')
    p.add_argument('--check', action='store_true', help='Install only: read-only dependency/compatibility checks')
    p.add_argument('--purge-credentials', action='store_true', help='Uninstall only: remove just AAG stored password')
    p.add_argument('--dry-run', action='store_true', help='Uninstall only: validate scope without deleting files')
    args = p.parse_args()
    if args.system:
        if os.geteuid() != 0: p.error('--system requires administrator execution')
        root = Path('/')
    else:
        if args.root.is_symlink(): p.error('Staging root cannot be a symlink')
        root = args.root.absolute()
        if root == Path('/'): p.error('Use --system explicitly for the host filesystem')
        if root != root.resolve(): p.error('Staging path cannot traverse symlinks')
        root.mkdir(parents=True, exist_ok=True)
    if args.purge_credentials and args.action != 'uninstall': p.error('Purge is only for uninstall')
    if args.dry_run and args.action != 'uninstall': p.error('Dry-run is only for uninstall')
    try:
        if (args.rebind or args.wifi_interface or args.check) and args.action != 'install':
            raise RuntimeError('Binding/check options are installation-only')
        if args.check:
            sys.path.insert(0, str(PROJECT / 'scripts'))
            import host_environment
            host_environment.detect(args.wifi_interface)
            print(json.dumps({'compatible': True, 'network_changes': False, 'secrets_read': False}))
            return 0
        if args.action == 'uninstall' and installed_receipt(root) is None:
            print(json.dumps({'removed_files': 0, 'status': 'NOT_INSTALLED'}))
            return 0
        if args.system and args.action == 'uninstall' and not args.dry_run:
            stop_for_uninstall()
        context = nullcontext()
        if args.system:
            # Share the backend's exact bounded operation lock, so package replacement
            # cannot race an activation or cleanup already in progress.
            sys.path.insert(0, str(PROJECT / 'lib'))
            from aag_hotspot.state import Store
            context = Store().locked(create=not args.dry_run)
        with context:
            result = install(root, args.system, args.wifi_interface, args.rebind) if args.action == 'install' else uninstall(root, args.system, args.purge_credentials, args.dry_run)
        print(json.dumps(result))
    except Exception as exc:
        print('Package action stopped: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
