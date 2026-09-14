#!/usr/bin/python3
"""Install/uninstall only a disposable prefix, from an extracted release archive."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def run(args,cwd):
    r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=60)
    if r.returncode:raise RuntimeError('Artifact check failed: '+repr(args)+'\n'+r.stderr)
    return r.stdout


def main():
    path=Path(sys.argv[1]).resolve();checks={}
    with tempfile.TemporaryDirectory(prefix='aag-public-artifact-') as tmp:
        base=Path(tmp)
        with tarfile.open(path) as archive:
            members=archive.getmembers()
            names=[m.name for m in members]
            assert len(names)==len(set(names))
            assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts and m.size<2*1024*1024 for m in members)
            assert all(not any(p in ('.git','reports','credentials.json','host.json','__pycache__') for p in Path(m.name).parts) for m in members)
            archive.extractall(base,filter='data')
        roots=list(base.iterdir());assert len(roots)==1;source=roots[0];prefix=base/'prefix'
        checks['archive_public_only']=True
        for name in ('install.sh','uninstall.sh'):run(['/bin/sh','-n',name],source)
        checks['shell_syntax']=True
        first=json.loads(run(['./install.sh','--root',str(prefix)],source))
        second=json.loads(run(['./install.sh','--root',str(prefix)],source))
        assert first['staging'] and not first['activation'] and second['changed_files']==0
        checks['staged_install_idempotent']=True
        expected=['usr/bin/aag-hotspot','usr/bin/aag-hotspot-gui','usr/libexec/aag-hotspot-helper','usr/share/applications/org.aag.Hotspot.desktop','usr/share/polkit-1/actions/org.aag.hotspot.policy','usr/lib/aag-hotspot/aag_hotspot/binding.py']
        assert all((prefix/name).is_file() for name in expected)
        checks['installed_layout']=True
        run(['/usr/bin/desktop-file-validate',str(prefix/'usr/share/applications/org.aag.Hotspot.desktop')],source)
        checks['desktop_entry']=True
        run([str(prefix/'usr/bin/aag-hotspot'),'--help'],source)
        dry=json.loads(run([str(prefix/'usr/bin/aag-hotspot'),'internet','--dry-run','--json'],source))
        assert dry.get('dry_run') is True
        checks['cli_no_activation']=True
        run(['/usr/bin/python3','scripts/check-static.py'],source)
        run(['/usr/bin/python3','-m','unittest','discover','-s','tests'],source)
        checks['extracted_static_and_regression']=True
        sentinel=prefix/'etc/NetworkManager/system-connections/Hotspot.nmconnection';sentinel.parent.mkdir(parents=True);sentinel.write_text('synthetic unrelated profile')
        credential=prefix/'var/lib/aag-hotspot/credentials.json';credential.parent.mkdir(parents=True);credential.write_text('synthetic preserved credential')
        before=sentinel.read_bytes();secret_hash=hashlib.sha256(credential.read_bytes()).hexdigest()
        inspection=json.loads(run(['./uninstall.sh','--root',str(prefix),'--dry-run'],source));assert inspection['dry_run']
        result=json.loads(run(['./uninstall.sh','--root',str(prefix)],source));assert result['credentials_preserved']
        assert sentinel.read_bytes()==before and hashlib.sha256(credential.read_bytes()).hexdigest()==secret_hash
        assert all(not (prefix/name).exists() for name in expected)
        again=json.loads(run(['./uninstall.sh','--root',str(prefix)],source));assert again['status']=='NOT_INSTALLED'
        checks['uninstall_scope_and_idempotency']=True
        checks['production_commands_executed']=False
    result={'passed':all(v for k,v in checks.items() if k!='production_commands_executed'),'checks':checks}
    print(json.dumps(result));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
