"""Short-lived, explicitly authorized password UI; no network operations."""
from .i18n import _, ngettext
from .ui_support import text_direction
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, Gtk

HIDE_SECONDS = 30
EXPIRE_SECONDS = 60


class SecretDialog(Adw.Dialog):
    def __init__(self, secret, clipboard):
        super().__init__(title=_('Wi-Fi password'), content_width=360)
        self.set_direction(text_direction())
        self.clipboard = clipboard
        self.provider = None
        self.hide_timer = self.copy_timer = self.expire_timer = 0
        self.cleared = False
        self.buffer = Gtk.PasswordEntryBuffer()
        try:
            self.buffer.set_text(secret.decode('ascii'), -1)
        finally:
            secret[:] = b'\0' * len(secret)
        self.field = Gtk.Entry(buffer=self.buffer, visibility=False, editable=False,
                               input_purpose=Gtk.InputPurpose.PASSWORD)
        self.field.set_direction(Gtk.TextDirection.LTR)
        self.show = Gtk.Button(label=_('Show'))
        self.show.connect('clicked', self.toggle)
        self.copy = Gtk.Button(label=_('Copy'), tooltip_text=_('Copy password'))
        self.copy.connect('clicked', self.copy_password)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + edge)(24)
        box.append(Gtk.Label(label=_('Wi-Fi password')))
        box.append(self.field)
        buttons = Gtk.Box(spacing=12, homogeneous=True)
        buttons.append(self.show); buttons.append(self.copy); box.append(buttons)
        self.message = Gtk.Label(label=_('The password hides after 30 seconds. This dialog closes after one minute.'), wrap=True)
        box.append(self.message)
        close = Gtk.Button(label=_('Close'))
        close.connect('clicked', lambda _: self.close())
        box.append(close); self.set_child(box)
        self.connect('closed', lambda _: self.clear())
        self.clip_changed = clipboard.connect('changed', self.clipboard_changed)
        self.expire_timer = GLib.timeout_add_seconds(EXPIRE_SECONDS, self.expire)

    def cancel_timer(self, name):
        timer = getattr(self, name)
        if timer:
            GLib.source_remove(timer)
            setattr(self, name, 0)

    def hide_password(self):
        self.cancel_timer('hide_timer')
        self.field.set_visibility(False)
        self.show.set_label(_('Show'))
        return False

    def toggle(self, *_args):
        if self.cleared: return
        if self.field.get_visibility(): self.hide_password()
        else:
            self.field.set_visibility(True)
            self.show.set_label(_('Hide'))
            self.hide_timer = GLib.timeout_add_seconds(HIDE_SECONDS, self.hide_password)

    def clipboard_changed(self, *_):
        # Never read or overwrite clipboard content supplied by another app.
        if self.provider is not None and self.clipboard.get_content() != self.provider:
            self.provider = None
            self.cancel_timer('copy_timer')

    def clear_clipboard(self):
        self.cancel_timer('copy_timer')
        provider, self.provider = self.provider, None
        if provider is not None and self.clipboard.get_content() == provider:
            self.clipboard.set_content(None)
        return False

    def copy_password(self, *_args):
        if self.cleared: return
        self.clear_clipboard()
        self.provider = Gdk.ContentProvider.new_for_value(self.buffer.get_text())
        if self.clipboard.set_content(self.provider):
            self.copy_timer = GLib.timeout_add_seconds(HIDE_SECONDS, self.clear_clipboard)
            self.message.set_label(_('Password copied. The clipboard copy expires after 30 seconds or when this dialog closes.'))
        else:
            self.provider = None
            self.message.set_label(_('Could not copy to the clipboard.'))

    def clear(self):
        if self.cleared: return
        self.cleared = True
        self.hide_password()
        self.cancel_timer('expire_timer')
        self.clear_clipboard()
        self.clipboard.disconnect(self.clip_changed)
        self.buffer.set_text('', 0)
        self.show.set_sensitive(False); self.copy.set_sensitive(False)

    def expire(self):
        self.expire_timer = 0
        self.clear()
        self.close()
        return False
