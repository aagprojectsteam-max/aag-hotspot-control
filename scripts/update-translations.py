#!/usr/bin/python3
"""Extract English gettext messages and compile maintained catalogs locally."""
from pathlib import Path
import subprocess
import re
ROOT=Path(__file__).resolve().parents[1]
MODULES=('gui.py','secret_dialog.py','tray.py','ui_support.py','i18n.py')


def main():
    template=ROOT/'po/aag-hotspot.pot'
    subprocess.run(['xgettext','--language=Python','--from-code=UTF-8','--keyword=_','--keyword=ngettext:1,2',
                    '--package-name=AAG Hotspot','--package-version=0.3.0','--no-location','-o',str(template),
                    *[str(ROOT/'lib/aag_hotspot'/name) for name in MODULES]],check=True,timeout=20)
    text=template.read_text().replace('SOME DESCRIPTIVE TITLE.','English source messages for AAG Hotspot.')
    text=text.replace("Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER",'Copyright (C) AAG Hotspot contributors')
    text=text.replace('FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.','AAG Hotspot contributors.')
    text=text.replace('FULL NAME <EMAIL@ADDRESS>','AAG Hotspot contributors')
    text=re.sub(r'("Language-Team: )[^"\\]*(\\n")',r'\1Translation contributors\2',text)
    template.write_text(text)
    for po in sorted((ROOT/'po').glob('*.po')):
        # Compiled resources are shipped so end users do not need gettext tools.
        target=ROOT/'lib/aag_hotspot/locale'/po.stem/'LC_MESSAGES/aag-hotspot.mo'
        target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['msgfmt','--check','-o',str(target),str(po)],check=True,timeout=15)


if __name__=='__main__':main()
