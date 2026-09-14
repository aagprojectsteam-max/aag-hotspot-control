"""Validated local hardware/profile binding, written only by the installer.

No secrets, shell expressions, firewall programs or uplink toggles are accepted.
An unbound source checkout can run tests/GUI; real activation fails closed.
"""
import json
import os
from pathlib import Path
import re
import stat
import uuid

PATH = Path(__file__).resolve().parents[1] / 'host.json'
# Reserved synthetic values for offline regression fixtures, never real profiles.
UNBOUND = {'schema': 1, 'wifi_interface': 'wlan0', 'phy': 0,
           'cellular_uuid': 'f0000001-0000-4000-8000-000000000001',
           'protected_uuids': ['f0000001-0000-4000-8000-000000000001',
                               'f0000002-0000-4000-8000-000000000002']}


def valid_uuid(value):
    try: return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError): return False


def validate(value):
    if not isinstance(value, dict) or set(value) != set(UNBOUND) or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid host binding schema')
    if not isinstance(value['wifi_interface'], str) or not re.fullmatch(r'wl[A-Za-z0-9_]{1,13}', value['wifi_interface']):
        raise ValueError('Invalid Wi-Fi interface binding')
    if type(value['phy']) is not int or not 0 <= value['phy'] <= 255:
        raise ValueError('Invalid Wi-Fi physical radio binding')
    ids = value['protected_uuids']
    if not isinstance(ids, list) or len(ids) > 2048 or not all(valid_uuid(x) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Invalid protected profile bindings')
    cell = value['cellular_uuid']
    if cell is not None and (not valid_uuid(cell) or cell not in ids):
        raise ValueError('Invalid cellular connection binding')
    return value


def load(path=PATH):
    try:
        # System installation is root-owned. Never trust a writable ancestor.
        for parent in (path.parent, *path.parents):
            st = parent.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                return dict(UNBOUND), False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o644 or st.st_size > 65536:
                return dict(UNBOUND), False
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError('Duplicate binding key')
                    result[key] = value
                return result
            return validate(json.load(stream, object_pairs_hook=unique)), True
    except (OSError, ValueError, TypeError):
        return dict(UNBOUND), False


HOST, READY = load()
STA = HOST['wifi_interface']
PHY = HOST['phy']
CELL_UUID = HOST['cellular_uuid']
PROTECTED_UUIDS = frozenset(HOST['protected_uuids'])
