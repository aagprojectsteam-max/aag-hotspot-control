"""Presentation-only helpers and per-user window geometry; no network access."""
import json
import os
from pathlib import Path
import stat
import tempfile
from . import i18n
from .i18n import _, ngettext

DEFAULT_SIZE = (440, 560)
MIN_SIZE = (360, 440)


def duration_label(seconds):
    if type(seconds) is not int or seconds < 0: return _('Unknown')
    if seconds < 60: return ngettext('{count} second', '{count} seconds', seconds).format(count=seconds)
    minutes = seconds // 60
    if minutes < 60: return ngettext('{count} minute', '{count} minutes', minutes).format(count=minutes)
    hours, minutes = divmod(minutes, 60)
    remainder = ngettext('{count} minute', '{count} minutes', minutes).format(count=minutes)
    whole = ngettext('{count} hour', '{count} hours', hours).format(count=hours)
    return _('{hours}, {minutes}').format(hours=whole, minutes=remainder) if minutes else whole


def text_direction(language=None):
    from gi.repository import Gtk
    return Gtk.TextDirection.RTL if i18n.direction(language) == 'rtl' else Gtk.TextDirection.LTR


def icon_directory():
    source = Path(__file__).resolve().parents[2] / 'desktop/icons/hicolor/scalable/status'
    return source if source.is_dir() else Path('/usr/share/icons/hicolor/scalable/status')


def icon_name(mode):
    return 'aag-hotspot-' + (mode if mode in ('off', 'internet', 'local') else 'off') + '-symbolic'


class Geometry:
    """Geometry only: never window contents, credentials, clients or networks."""
    def __init__(self, path): self.path = Path(path)

    @staticmethod
    def valid(value):
        return (isinstance(value, dict) and set(value) == {'width', 'height', 'maximized'}
                and type(value['width']) is int and MIN_SIZE[0] <= value['width'] <= 1920
                and type(value['height']) is int and MIN_SIZE[1] <= value['height'] <= 1440
                and type(value['maximized']) is bool)

    def load(self):
        default = {'width': DEFAULT_SIZE[0], 'height': DEFAULT_SIZE[1], 'maximized': False}
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd) as stream:
                st = os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > 4096: return default
                value = json.load(stream)
            return value if self.valid(value) else default
        except (OSError, ValueError): return default

    def save(self, width, height, maximized):
        value = {'width': width, 'height': height, 'maximized': maximized}
        if not self.valid(value): return False
        temp = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            st = self.path.parent.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022: return False
            fd, temp = tempfile.mkstemp(prefix='.window-', dir=self.path.parent)
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream); stream.write('\n')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.path)
            return True
        except OSError: return False
        finally:
            if temp:
                try: os.unlink(temp)
                except FileNotFoundError: pass
