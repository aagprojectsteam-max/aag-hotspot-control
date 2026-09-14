#!/usr/bin/python3
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
if os.geteuid() != 0 or BASE != Path('/usr/lib/aag-hotspot'):
    raise SystemExit('Supervisor requires the installed administrator package')
sys.path.insert(0, str(BASE))
from aag_hotspot.helper import watch
raise SystemExit(watch())
