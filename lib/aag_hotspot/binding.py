"""Validated local AP radio binding, written only by the installer.

No connection UUID, uplink identity, secret or execution option is accepted.
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
UNBOUND = {'schema': 2, 'wifi_interface': 'wlan0', 'phy': 0}


def valid_uuid(value):
    try: return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError): return False


def validate(value):
    if not isinstance(value, dict) or set(value) != set(UNBOUND) or type(value['schema']) is not int or value['schema'] != 2:
        raise ValueError('Invalid host binding schema')
    if not isinstance(value['wifi_interface'], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', value['wifi_interface']):
        raise ValueError('Invalid Wi-Fi interface binding')
    if type(value['phy']) is not int or not 0 <= value['phy'] <= 255:
        raise ValueError('Invalid Wi-Fi physical radio binding')
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
# All pre-existing profiles are protected by each session's baseline inventory.
PROTECTED_UUIDS = frozenset()
