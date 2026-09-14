#!/usr/bin/python3
"""Install only the reviewed GUI, tray, UI support and symbolic icons.

Never runs the package installer, helper, NetworkManager, systemctl or firewall
commands. Existing backend receipt entries/bytes/modes/mtimes remain identical.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ui_package_files',ROOT/'scripts/package.py')
pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)
UI_MODULES=('gui.py','tray.py','ui_support.py')
ICON_NAMES=tuple('aag-hotspot-'+mode+'-symbolic.svg' for mode in ('off','internet','local'))


def payloads():
    files={Path('usr/lib/aag-hotspot/aag_hotspot')/name:ROOT/'lib/aag_hotspot'/name for name in UI_MODULES}
    files.update({Path('usr/share/icons/hicolor/scalable/status')/name:ROOT/'desktop/icons/hicolor/scalable/status'/name for name in ICON_NAMES})
    return files


def inventory(root, receipt, excluded=()):
    result={}
    for rel,meta in receipt['files'].items():
        if Path(rel) in excluded:continue
        path=pkg.checked_path(root,Path(rel));st=path.stat()
        result[rel]={'sha256':pkg.digest(path),'mode':stat.S_IMODE(st.st_mode),'mtime_ns':st.st_mtime_ns,
                     'uid':st.st_uid,'gid':st.st_gid}
        if result[rel]['sha256']!=meta['sha256'] or result[rel]['mode']!=meta['mode']:
            raise RuntimeError('Installed file differs from receipt; preserve for review')
    return result


def install(root):
    root=Path(root)
    receipt=pkg.installed_receipt(root)
    if not receipt:raise RuntimeError('Existing production package required')
    mapping=payloads()
    allowed={Path('usr/lib/aag-hotspot/aag_hotspot')/name for name in UI_MODULES}
    allowed|={Path('usr/share/icons/hicolor/scalable/status')/name for name in ICON_NAMES}
    if set(mapping)!=allowed:raise RuntimeError('UI update scope changed')
    all_before=inventory(root,receipt)
    unchanged=inventory(root,receipt,allowed)
    for relative in mapping:
        path=pkg.checked_path(root,relative)
        if path.exists() and str(relative) not in receipt['files']:raise RuntimeError('Unowned UI file preserved')
    # Dependencies first, then the importing views, and the receipt last.
    order=sorted(mapping,key=lambda p:(p.name in ('tray.py','gui.py'),p.name=='gui.py',str(p)))
    data={relative:mapping[relative].read_bytes() for relative in order}
    updated=json.loads(json.dumps(receipt));pending={}
    for relative in order:
        updated['files'][str(relative)]={'sha256':hashlib.sha256(data[relative]).hexdigest(),'mode':0o644}
        path=pkg.checked_path(root,relative)
        if not path.exists() or path.read_bytes()!=data[relative] or stat.S_IMODE(path.stat().st_mode)!=0o644:
            pending[path]=(data[relative],0o644)
    manifest=pkg.checked_path(root,pkg.MANIFEST)
    record=(json.dumps(updated,indent=2)+'\n').encode()
    if manifest.read_bytes()!=record:pending[manifest]=(record,0o644)
    backups={p:(p.read_bytes(),stat.S_IMODE(p.stat().st_mode)) if p.exists() else None for p in pending}
    changed=[]
    try:
        for path,(contents,mode) in pending.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            pkg.checked_path(root,path.relative_to(root))
            pkg.atomic_file(path,contents,mode);changed.append(path)
        if unchanged!=inventory(root,updated,allowed):raise RuntimeError('Non-UI installed state changed')
        matches={str(relative):pkg.digest(pkg.checked_path(root,relative))==hashlib.sha256(data[relative]).hexdigest() for relative in data}
        if not all(matches.values()):raise RuntimeError('Installed UI mismatch')
    except BaseException:
        for path in reversed(changed):
            if backups[path] is None:path.unlink()
            else:pkg.atomic_file(path,*backups[path])
        raise
    return {'installed_source_match':all(matches.values()),'changed_files':len(changed),
            'installed_files':matches,'non_ui_files_unchanged':len(unchanged),
            'network_commands_executed':False,'helper_invoked':False,'backend_installed':False,'autostart_added':False}


def main():
    if os.geteuid()!=0 or len(sys.argv)!=1:
        print('Administrator UI update entry without arguments required');return 2
    os.umask(0o022)
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        result=install(Path('/'))
        repeat=install(Path('/'))
        result['installer_idempotent']=repeat['changed_files']==0
        result['ok']=result['installed_source_match'] and result['installer_idempotent']
        print(json.dumps(result));return 0 if result['ok'] else 1
    except Exception as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__,'network_commands_executed':False}));return 1


if __name__=='__main__':raise SystemExit(main())
