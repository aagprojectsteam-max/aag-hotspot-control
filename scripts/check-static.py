#!/usr/bin/python3
"""Unprivileged syntax/launcher/polkit checks; never executes application actions."""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    python_files = sorted([*ROOT.glob('lib/**/*.py'), *ROOT.glob('scripts/*.py'),
                           *ROOT.glob('tests/*.py'), *ROOT.glob('gui/*.py')])
    shells = []
    for path in [*ROOT.glob('bin/*'), *ROOT.glob('scripts/*.sh'), *ROOT.glob('*.sh')]:
        shebang = path.read_text().splitlines()[0]
        if 'python' in shebang: python_files.append(path)
        else: shells.append((path, '/bin/bash' if 'bash' in shebang else '/bin/sh'))
    for path in python_files: ast.parse(path.read_text(), filename=str(path))
    for path, interpreter in shells:
        subprocess.run([interpreter, '-n', str(path)], check=True, timeout=10)
    shellcheck = shutil.which('shellcheck')
    if shellcheck:
        subprocess.run([shellcheck, *[str(path) for path, _ in shells]], check=True, timeout=30)
    subprocess.run(['/usr/bin/desktop-file-validate', str(ROOT / 'desktop/org.aag.Hotspot.desktop')], check=True, timeout=10)
    actions = ET.parse(ROOT / 'polkit/org.aag.hotspot.policy').getroot().findall('action')
    assert len(actions) == 1 and actions[0].attrib['id'] == 'org.aag.hotspot.control'
    action = actions[0]
    assert action.findtext('defaults/allow_any') == 'no'
    assert action.findtext('defaults/allow_inactive') == 'no'
    assert action.findtext('defaults/allow_active') == 'auth_admin_keep'
    assert action.find('annotate').text == '/usr/libexec/aag-hotspot-helper'
    assert not re.search(r'^\s*\[Install\]\s*$', (ROOT / 'systemd/aag-hotspot-watch.service').read_text(), re.M)
    print(json.dumps({'python_syntax_files': len(python_files), 'shell_syntax_files': len(shells),
                      'desktop_entry': 'PASS', 'polkit_fixed_scope': 'PASS', 'autostart': False,
                      'shellcheck': 'PASS' if shellcheck else 'NOT_INSTALLED', 'passed': True}))


if __name__ == '__main__': main()
