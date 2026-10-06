"""Application gettext domain and unprivileged per-user language preferences.

English is the source language, independent of the desktop locale. Only the GUI
loads preferences; the CLI/helper never imports or consults this module.
"""
import gettext
import json
import os
from pathlib import Path
import stat
import tempfile

DOMAIN = 'aag-hotspot'
LANGUAGES = {'en': 'ltr', 'he': 'rtl'}
LOCALE_DIR = Path(__file__).resolve().parent / 'locale'
_language = 'en'
_catalog = gettext.NullTranslations()


def catalog(language):
    if language not in LANGUAGES:
        raise ValueError('Unsupported application language')
    if language == 'en': return gettext.NullTranslations()
    return gettext.translation(DOMAIN, str(LOCALE_DIR), languages=[language])


def set_language(language):
    global _language, _catalog
    translated = catalog(language)
    _language, _catalog = language, translated


def language(): return _language
def direction(language=None): return LANGUAGES[language or _language]
def _(message): return _catalog.gettext(message)
def ngettext(singular, plural, count): return _catalog.ngettext(singular, plural, count)


def language_options():
    # Native language names live in each language's translation catalog.
    return [('en', catalog('en').gettext('English')), ('he', catalog('he').gettext('Hebrew'))]


def read_user_json(path):
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o022:
        raise ValueError('Untrusted preferences directory')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or st.st_mode & 0o077 or st.st_nlink != 1 or st.st_size > 4096):
            raise ValueError('Untrusted preferences file')
        return json.load(stream)


class LanguageSettings:
    def __init__(self, directory=None, initial='en'):
        self.directory = Path(directory) if directory is not None else None
        self.language, self.migrated, self.error = initial, False, False
        if initial not in LANGUAGES: raise ValueError('Unsupported application language')
        if self.directory is not None: self.load()

    def load(self):
        path = self.directory / 'preferences.json'
        try:
            value = read_user_json(path)
            if (not isinstance(value, dict) or set(value) != {'schema', 'language'}
                    or type(value['schema']) is not int or value['schema'] != 1
                    or value['language'] not in LANGUAGES):
                raise ValueError('Invalid preferences')
            self.language = value['language']
            return
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.language, self.error = 'en', True
            return
        # Earlier Hebrew-only GUIs saved this validated, private geometry file.
        # Mere package/credential existence never migrates a fresh user to Hebrew.
        try:
            from .ui_support import Geometry
            self.migrated = Geometry.valid(read_user_json(self.directory / 'window.json'))
        except (OSError, ValueError, TypeError):
            self.migrated = False
        self.language = 'he' if self.migrated else 'en'
        self.error = not self.save(self.language)

    def save(self, language):
        if language not in LANGUAGES: return False
        if self.directory is None:
            self.language = language
            return True
        temp = None
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            st = self.directory.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
                return False
            path = self.directory / 'preferences.json'
            if path.is_symlink(): return False
            fd, temp = tempfile.mkstemp(prefix='.language-', dir=self.directory)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'schema': 1, 'language': language}, stream)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
            self.language, self.error = language, False
            return True
        except OSError:
            return False
        finally:
            if temp is not None:
                try: os.unlink(temp)
                except FileNotFoundError: pass
