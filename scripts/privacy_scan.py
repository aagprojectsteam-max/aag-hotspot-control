#!/usr/bin/python3
"""Fail on private identifiers/material; never print matched values."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','dist','build','__pycache__','.venv'}
PATTERNS={
    'personal_home':r'/home/(?!runner(?:/|\b)|example-user(?:/|\b))[\w.-]+',
    'developer_mount':r'/mnt/(?:data|private)/',
    'magicdns':r'\b[\w.-]+\.ts\.net\b',
    'private_key':r'-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----',
    'token':r'\b(?:gh[pousr]_|github_pat_|sk-proj-)[A-Za-z0-9_]{20,}',
    'email':r'\b[A-Za-z0-9_.+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'carrier_ip':r'\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d+\.\d+\b',
}
RULES={key:re.compile(value) for key,value in PATTERNS.items()}
UUID=re.compile(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b')
MAC=re.compile(r'\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b')
PUBLIC_COMMIT_EMAILS={b'aag.projects.team@gmail.com'}


def findings(data, name):
    problems=[]
    if len(data)>2*1024*1024:problems.append('large_file')
    if any(part in ('credentials.json','host.json','.env') or part.endswith(('.pem','.key','.nmconnection','.secret')) for part in Path(name).parts):problems.append('private_file')
    if b'\0' in data:return problems
    value=data.decode('utf-8','replace')
    problems += [key for key,rx in RULES.items() if rx.search(value.replace('100.64.0.0/10', 'CGNAT_NETWORK'))]
    if any(not re.fullmatch(r'f[0-9a-f]{7}-0000-4000-8000-[0-9a-f]{12}',x) for x in UUID.findall(value)):problems.append('non_fixture_uuid')
    if any(not (int(x[:2],16)&2 or x.lower() in ('01:00:00:00:00:01','00:00:00:00:00:00')) for x in MAC.findall(value)):problems.append('non_fixture_mac')
    return sorted(set(problems))


def scan(history=False):
    issues=[];count=0
    if history:
        records=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=ROOT,text=True).splitlines()
        for record in records:
            oid,_,name=record.partition(' ')
            if subprocess.check_output(['git','cat-file','-t',oid],cwd=ROOT,text=True).strip()!='blob':continue
            categories=findings(subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT),name);count+=1
            if categories:issues.append({'path':name,'categories':categories})
        metadata=subprocess.check_output(['git','log','--all','--format=%an <%ae>%n%cn <%ce>%n%B'],cwd=ROOT)
        for email in PUBLIC_COMMIT_EMAILS:
            metadata=metadata.replace(email,b'public-project-identity@users.noreply.github.com')
        categories=findings(metadata,'commit-metadata')
        if categories:issues.append({'path':'commit-metadata','categories':categories})
    else:
        for path in sorted(ROOT.rglob('*')):
            rel=path.relative_to(ROOT)
            if set(rel.parts)&SKIP:continue
            if path.is_symlink():issues.append({'path':str(rel),'categories':['symlink']});continue
            if not path.is_file():continue
            categories=findings(path.read_bytes(),str(rel));count+=1
            if categories:issues.append({'path':str(rel),'categories':categories})
    return {'passed':not issues,'history':history,'files_or_blobs':count,'issues':issues}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--history',action='store_true');args=p.parse_args()
    result=scan(args.history);print(json.dumps(result,indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
