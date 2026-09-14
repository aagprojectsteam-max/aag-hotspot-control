#!/usr/bin/python3
"""Installed entry point; root never imports from user-owned source paths."""
import os
from pathlib import Path
import stat
import sys
sys.dont_write_bytecode = True

BASE = Path(__file__).resolve().parent
if os.geteuid() == 0:
    if BASE != Path('/usr/lib/aag-hotspot'):
        raise SystemExit('Privileged execution requires the installed root-owned package')
    for p in (BASE, BASE / 'aag_hotspot', *list((BASE / 'aag_hotspot').glob('*.py'))):
        st = p.lstat()
        if st.st_uid != 0 or stat.S_ISLNK(st.st_mode) or st.st_mode & 0o022:
            raise SystemExit('Untrusted installed application code')
sys.path.insert(0, str(BASE))
from aag_hotspot.helper import main
raise SystemExit(main())
