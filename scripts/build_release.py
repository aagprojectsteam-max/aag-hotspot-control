#!/usr/bin/python3
"""Deterministic public archive, file manifest and SHA256SUMS; no installation."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.2.0'
TOP='aag-hotspot-control-v'+VERSION
DIRECTORIES={'bin','lib','desktop','polkit','systemd','config','docs','scripts','tests','.github'}
TOP_FILES={'README.md','LICENSE','CHANGELOG.md','SECURITY.md','CONTRIBUTING.md','THIRD_PARTY.md','RELEASE_NOTES.md','.gitignore','install.sh','uninstall.sh'}


def inputs():
    files=[]
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT)
        if rel.parts[0] not in DIRECTORIES and str(rel) not in TOP_FILES:continue
        if '__pycache__' in rel.parts or path.suffix=='.pyc':continue
        if path.is_symlink():raise RuntimeError('Symlink forbidden in release')
        if path.is_file():files.append((rel,path))
    if not TOP_FILES.issubset({str(rel) for rel,_ in files}):raise RuntimeError('Missing required public files')
    return sorted(files)


def main():
    from privacy_scan import scan
    if not scan()['passed']:raise RuntimeError('Privacy scan failed; no release built')
    try:
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,stderr=subprocess.DEVNULL,text=True).strip()
        epoch=int(subprocess.check_output(['git','show','-s','--format=%ct','HEAD'],cwd=ROOT,text=True))
        # Do not accidentally take a parent development repository's identity.
        gitroot=subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True).strip()
        if Path(gitroot)!=ROOT:raise ValueError('Not the public repository')
    except (subprocess.CalledProcessError,ValueError):
        revision=(ROOT/'SOURCE_REVISION').read_text().strip() if (ROOT/'SOURCE_REVISION').exists() else 'UNCOMMITTED'
        epoch=0
    payload={str(rel):(path.read_bytes(),0o755 if path.stat().st_mode&0o111 else 0o644) for rel,path in inputs()}
    payload['SOURCE_REVISION']=((revision+'\n').encode(),0o644)
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    archive=out/(TOP+'.tar.gz')
    with archive.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=epoch) as zipped,tarfile.open(fileobj=zipped,mode='w',format=tarfile.PAX_FORMAT) as tar:
        for rel,(data,mode) in sorted(payload.items()):
            info=tarfile.TarInfo(TOP+'/'+rel);info.size=len(data);info.mode=mode;info.mtime=epoch;info.uid=info.gid=0;info.uname=info.gname=''
            tar.addfile(info,io.BytesIO(data))
    manifest={'schema':1,'project':'AAG Hotspot Control','version':VERSION,'tag':'v'+VERSION,'commit':revision,
              'archive':{'name':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size},
              'files':[{'path':rel,'mode':oct(mode),'sha256':hashlib.sha256(data).hexdigest()} for rel,(data,mode) in sorted(payload.items())]}
    manifest_path=out/'release-manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (archive,manifest_path)))
    print(json.dumps({'archive':archive.name,'files':len(payload),'commit':revision,'sha256':manifest['archive']['sha256']}))


if __name__=='__main__':main()
