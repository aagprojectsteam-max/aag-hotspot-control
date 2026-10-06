"""Translated GNOME views; the existing client transport owns all network state."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Pango
from . import client, i18n
from .i18n import _, ngettext
from .policy import validate_password
from .clients import expire, hostname, ipv4_address, mac_address
from .ui_support import Geometry, DEFAULT_SIZE, MIN_SIZE, duration_label, icon_directory, icon_name, text_direction
from .secret_dialog import SecretDialog


def presentation(value):
    modes = {'off': _('Hotspot is off'), 'local': _('Local only'), 'internet': _('Internet hotspot')}
    state = modes.get(value.get('mode'), _('Unknown status'))
    if value.get('phase') in ('starting', 'switching'): state = _('Updating hotspot…')
    if value.get('phase') == 'stopping': state = _('Turning off hotspot…')
    uplink = value.get('uplink')
    kind=value.get('uplink_type','NONE')
    source={'CELLULAR':_('Cellular'),'ETHERNET':_('Ethernet'),'WIFI':_('Wi-Fi (UNVALIDATED)'),
            'NONE_REQUIRED':_('No Internet connection required')}.get(kind,_('No supported connection'))
    connection=value.get('uplink_connection')
    if connection and kind in ('CELLULAR','ETHERNET','WIFI'):source += ' · '+connection
    count = value.get('clients')
    if value.get('health') in ('UNKNOWN', 'ERROR', 'NOT_INSTALLED'):
        state, count = _('Hotspot status unavailable'), None
    return {'mode': state, 'ssid': value.get('ssid', 'AAG-Hotspot'), 'source': source,
            'clients': str(count) if type(count) is int and count >= 0 else _('Unknown')}


def error_message(error):
    if not error: return ''
    if 'INSTALLATION_REQUIRED' in error: return _('Install AAG Hotspot before turning on the hotspot.')
    if 'AUTHENTICATION' in error: return _('Authorization was cancelled or denied. This request did not change your hotspot.')
    if 'WIFI_STA_UNVALIDATED' in error: return _('Your existing Wi-Fi connection was preserved. Wi-Fi uplink sharing is not yet supported.')
    if 'UNSUPPORTED_UPLINK' in error or 'UPLINK_UNSUPPORTED' in error: return _('The current Internet connection cannot be shared safely. You can use local-only mode.')
    if 'WIFI_DEVICE_BUSY' in error: return _('The Wi-Fi adapter is already in use. Your existing connection was preserved.')
    if 'UPLINK_CHANGED' in error or 'FORWARD_ROUTE_MISMATCH' in error: return _('The Internet route changed. The hotspot was stopped safely. Try again to use the current connection.')
    if 'CELLULAR_REQUIRED' in error: return _('A supported cellular Internet connection is required. You can use local-only mode instead.')
    if 'CONFIGURATION_REQUIRED' in error: return _('Set a hotspot password first.')
    if 'RFKILL' in error or 'hardware radio is blocked' in error: return _('Wi-Fi is blocked. Check the wireless switch or airplane mode.')
    if 'READINESS_TIMEOUT' in error: return _('The Wi-Fi adapter did not become ready in time. Check the network before trying again.')
    if 'NM_READINESS_UNAVAILABLE' in error: return _('NetworkManager is unavailable. Check that the network service is running.')
    if 'TIMEOUT' in error: return _('The operation timed out. Cleanup may still be running. Check the status before trying again.')
    if 'HELPER_' in error: return _('The hotspot service could not be reached. Check the application installation.')
    if 'BUSY' in error: return _('Another operation is running. Wait a moment, then refresh.')
    if 'STALE' in error or 'UNREADABLE' in error: return _('The hotspot status could not be verified. Refresh or open Diagnostics.')
    return _('The operation did not finish. Open Diagnostics to check the hotspot status.')


class Window(Adw.ApplicationWindow):
    def __init__(self, app, transport=client, geometry=None):
        Gtk.Widget.set_default_direction(text_direction())
        self.geometry = geometry or (Geometry(Path(GLib.get_user_config_dir()) / 'aag-hotspot/window.json') if transport is client else None)
        size = self.geometry.load() if self.geometry else dict(width=DEFAULT_SIZE[0], height=DEFAULT_SIZE[1], maximized=False)
        super().__init__(application=app, title=_('AAG Hotspot'), default_width=size['width'], default_height=size['height'])
        self.set_size_request(*MIN_SIZE)
        if size['maximized']: self.maximize()
        self.transport, self.pool = transport, ThreadPoolExecutor(max_workers=1)
        self.busy, self.refreshing, self.closed = False, False, False
        self.reveal_pending, self.reveal_generation, self.secret_view = False, 0, None
        self.settings_view = None
        self.current = {'configured': False}
        self.connect('close-request', self.on_close)
        self.set_direction(text_direction())
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(str(icon_directory()))
        self.actions = {}
        callbacks = {'refresh': self.refresh, 'password': self.password_dialog, 'diagnose': self.diagnose,
                     'reveal-password': self.reveal_password,
                     'settings': self.settings_dialog,
                     'about': self.about, 'clients': self.show_clients,
                     'mode-internet': lambda: self.activate_mode('internet'),
                     'mode-local': lambda: self.activate_mode('local'),
                     'quit': lambda: app.tray_action('quit') if hasattr(app, 'tray_action') else self.close()}
        for name, callback in callbacks.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=callback: fn())
            self.add_action(action); self.actions[name] = action
        self.build_view()
        self.timer = GLib.timeout_add_seconds(5, self.refresh)
        self.refresh()

    def build_view(self):
        """Rebuild presentation only; retain controller state, worker and timer."""
        self.navigation = Adw.NavigationView()
        self.menu_model = Gio.Menu()
        self.menu_model.append(_('Show password'), 'win.reveal-password')
        self.menu_model.append(_('Change password…'), 'win.password')
        self.menu_model.append(_('Diagnostics'), 'win.diagnose')
        self.menu_model.append(_('Refresh'), 'win.refresh')
        self.menu_model.append(_('Settings'), 'win.settings')
        extra = Gio.Menu(); extra.append(_('About AAG Hotspot'), 'win.about'); extra.append(_('Quit application'), 'win.quit')
        self.menu_model.append_section(None, extra)
        self.main_page = self.build_main()
        self.devices_page = self.build_devices()
        self.navigation.add(self.main_page)
        self.navigation.add(self.devices_page)
        self.set_content(self.navigation)

    def settings_dialog(self):
        if self.settings_view is not None:
            self.settings_view.present(self)
            return
        dialog = Adw.Dialog(title=_('Settings'), content_width=380)
        dialog.set_direction(text_direction())
        box = self.content_box()
        options = i18n.language_options()
        row = Adw.ComboRow(title=_('Language'), model=Gtk.StringList.new([name for _, name in options]))
        row.set_selected([code for code, _ in options].index(i18n.language()))
        # Language endonyms are individually LTR/RTL isolates in the selector.
        factory = Gtk.SignalListItemFactory()
        def setup(_factory, item): item.set_child(Gtk.Label(xalign=0))
        def bind(_factory, item):
            item.get_child().set_label(item.get_item().get_string())
            item.get_child().set_direction(text_direction(dict((name, code) for code, name in options)[item.get_item().get_string()]))
        factory.connect('setup', setup); factory.connect('bind', bind)
        row.set_factory(factory); row.set_list_factory(factory)
        group = Adw.PreferencesGroup(); group.add(row); box.append(group)
        help_text = Gtk.Label(wrap=True, xalign=0)
        box.append(help_text)
        self.settings_notice = Gtk.Label(wrap=True, xalign=0, visible=False)
        box.append(self.settings_notice)
        close = Gtk.Button(); close.connect('clicked', lambda _: dialog.close()); box.append(close)
        dialog.set_child(box)
        self.settings_view = dialog
        self.settings_widgets = (row, help_text, close)
        def closed(_):
            if self.settings_view is dialog: self.settings_view = None
        dialog.connect('closed', closed)
        def selected(*_args):
            code = options[row.get_selected()][0]
            if not self.change_language(code):
                row.set_selected([code for code, _ in options].index(i18n.language()))
        row.connect('notify::selected', selected)
        self.translate_settings()
        dialog.present(self)

    def translate_settings(self):
        if self.settings_view is None: return
        self.settings_view.set_title(_('Settings'))
        self.settings_view.set_direction(text_direction())
        row, help_text, close = self.settings_widgets
        row.set_title(_('Language'))
        help_text.set_label(_('Choose your language. Changes apply immediately without interrupting the hotspot.'))
        close.set_label(_('Close'))

    def change_language(self, language):
        if language == i18n.language(): return True
        try: i18n.catalog(language)
        except (OSError, ValueError): return False
        if not self.get_application().settings.save(language):
            self.notice.set_label(_('Your language preference could not be saved. The current language was kept.'))
            self.notice.set_visible(True)
            if self.settings_view is not None:
                self.settings_notice.set_label(self.notice.get_label()); self.settings_notice.set_visible(True)
            return False
        devices_visible = self.navigation.get_visible_page() is self.devices_page
        self.clear_secret()
        dialog = self.get_visible_dialog()
        if dialog is not None and dialog is not self.settings_view: dialog.close()
        i18n.set_language(language)
        Gtk.Widget.set_default_direction(text_direction())
        self.set_direction(text_direction())
        self.set_title(_('AAG Hotspot'))
        self.build_view()
        self.render(self.current)
        if devices_visible: self.navigation.push(self.devices_page)
        if self.busy:
            self.spinner.start()
            self.notice.set_label(_('Waiting for authorization and completion…')); self.notice.set_visible(True)
        self.translate_settings()
        if self.settings_view is not None: self.settings_notice.set_visible(False)
        # No transport call, status publication, mode command or GUI restart.
        return True

    def header(self, title, refresh=False):
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title))
        menu = Gtk.MenuButton(icon_name='open-menu-symbolic', tooltip_text=_('Menu'))
        menu.set_menu_model(self.menu_model)
        header.pack_end(menu)
        if refresh:
            button = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text=_('Refresh'))
            button.set_action_name('win.refresh'); header.pack_end(button)
        else:
            self.header_menu = menu
            self.spinner = Gtk.Spinner(visible=False)
            header.pack_end(self.spinner)
        return header

    @staticmethod
    def scroll_content(content, maximum=400):
        clamp = Adw.Clamp(maximum_size=maximum, tightening_threshold=360)
        clamp.set_child(content)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                   propagate_natural_width=False, propagate_natural_height=False)
        scroll.set_child(clamp)
        return scroll

    @staticmethod
    def content_box():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        for edge in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_' + edge)(24)
        return box

    def build_main(self):
        toolbar = Adw.ToolbarView(); toolbar.add_top_bar(self.header(_('AAG Hotspot')))
        content = self.content_box()
        summary = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.status_icon = Gtk.Image(icon_name=icon_name('off'), pixel_size=36, valign=Gtk.Align.START)
        summary.append(self.status_icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        self.mode = Gtk.Label(label=_('Loading…'), wrap=True, xalign=0)
        self.mode.add_css_class('title-2')
        self.description = Gtk.Label(wrap=True, xalign=0)
        self.description.add_css_class('dim-label')
        text.append(self.mode); text.append(self.description); summary.append(text); content.append(summary)
        self.info_group = Adw.PreferencesGroup()
        self.values, self.info_rows = {}, {}
        for key, title in [('ssid', _('Network name')), ('source', _('Internet source')), ('clients', _('Connected devices'))]:
            row = Adw.ActionRow(title=title)
            value = Gtk.Label(label='—', selectable=key=='ssid', valign=Gtk.Align.CENTER)
            value.set_max_width_chars(22)
            value.set_ellipsize(Pango.EllipsizeMode.END)
            value.set_direction(Gtk.TextDirection.LTR if key in ('ssid', 'clients') else text_direction())
            row.add_suffix(value)
            if key == 'clients':
                row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
                row.set_activatable(True)
                row.connect('activated', lambda _: self.show_clients())
            self.values[key], self.info_rows[key] = value, row
            self.info_group.add(row)
        content.append(self.info_group)
        self.reveal_button = Gtk.Button(label=_('Show password'), halign=Gtk.Align.END)
        self.reveal_button.add_css_class('flat')
        self.reveal_button.set_action_name('win.reveal-password')
        content.append(self.reveal_button)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.buttons = {}
        for action, label, style in [('internet', _('Share Internet'), 'suggested-action'),
                                     ('local', _('Local network only'), ''), ('off', _('Turn off hotspot'), 'destructive-action')]:
            button = Gtk.Button(label=label, height_request=44, visible=False)
            if style: button.add_css_class(style)
            button.connect('clicked', lambda _, name=action: self.activate_mode(name))
            self.buttons[action] = button; controls.append(button)
        self.switch_mode = Gtk.MenuButton(label=_('Switch mode'), halign=Gtk.Align.CENTER, visible=False)
        self.switch_mode.add_css_class('flat'); controls.append(self.switch_mode)
        content.append(controls)
        self.notice = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.notice.add_css_class('dim-label'); content.append(self.notice)
        self.main_scroll = self.scroll_content(content)
        toolbar.set_content(self.main_scroll)
        return Adw.NavigationPage.new(toolbar, _('AAG Hotspot'))

    def build_devices(self):
        toolbar = Adw.ToolbarView(); toolbar.add_top_bar(self.header(_('Connected devices'), refresh=True))
        self.client_stack = Gtk.Stack(vhomogeneous=False, hhomogeneous=False)
        self.empty_clients = Adw.StatusPage(title=_('No devices connected'),
                                          description=_('Devices connected to this hotspot will appear here.'), icon_name='computer-symbolic')
        self.empty_clients.add_css_class('compact')
        self.client_stack.add_named(self.empty_clients, 'empty')
        self.client_group = self.content_box(); self.client_rows = {}
        self.devices_scroll = self.scroll_content(self.client_group)
        self.client_stack.add_named(self.devices_scroll, 'list')
        toolbar.set_content(self.client_stack)
        return Adw.NavigationPage.new(toolbar, _('Connected devices'))

    def show_clients(self):
        if self.navigation.get_visible_page() is not self.devices_page: self.navigation.push(self.devices_page)
        self.refresh()

    def save_geometry(self):
        if self.geometry:
            width, height = self.get_default_size()
            self.geometry.save(width, height, self.is_maximized())

    def on_close(self, *_):
        self.clear_secret()
        self.save_geometry()
        app = self.get_application()
        if getattr(app, 'tray', None) is not None and app.tray.registered and not getattr(app, 'exiting', False):
            self.set_visible(False)
            return True
        self.dispose_view()
        return False

    def dispose_view(self):
        if self.closed: return
        self.clear_secret()
        self.save_geometry()
        self.closed = True
        GLib.source_remove(self.timer)
        self.pool.shutdown(wait=False)

    def dispatch(self, function, callback):
        future = self.pool.submit(function)
        def complete(f):
            try: value = f.result()
            except Exception: value = {'ok': False, 'error': 'REQUEST_FAILED'}
            def deliver():
                if not self.closed: callback(value)
                return False
            GLib.idle_add(deliver)
        future.add_done_callback(complete)

    def render(self, value):
        value = expire(dict(value)); self.current = value
        view = presentation(value)
        self.mode.set_label(view['mode'])
        mode, phase = value.get('mode'), value.get('phase')
        off = mode == phase == 'off'
        active = mode in ('internet', 'local') and phase == 'active' and value.get('health') == 'OK'
        self.description.set_label({'off': _('Choose how to use your hotspot.'),
                                    'internet': _('Share the current supported Internet connection.'),
                                    'local': _('Connect devices locally without sharing Internet access.')}.get(mode, ''))
        self.status_icon.set_from_icon_name(icon_name(mode))
        if mode == 'internet' and active: self.status_icon.add_css_class('accent')
        else: self.status_icon.remove_css_class('accent')
        for key, label in self.values.items(): label.set_label(view[key])
        self.info_rows['source'].set_visible(not off)
        self.info_rows['source'].set_title(_('Internet sharing') if mode == 'local' else _('Internet source'))
        if mode == 'local': self.values['source'].set_label(_('No'))
        self.values['source'].set_tooltip_text(view['source'])
        for action, button in self.buttons.items():
            button.set_visible((action in ('internet', 'local')) if off else action == 'off')
            button.set_sensitive(not self.busy)
        switch = Gio.Menu()
        alternate = 'local' if mode == 'internet' else 'internet'
        switch.append(_('Local only') if alternate == 'local' else _('Internet hotspot'), 'win.mode-' + alternate)
        self.switch_mode.set_menu_model(switch); self.switch_mode.set_visible(active)
        message = error_message(value.get('error')); self.notice.set_label(message); self.notice.set_visible(bool(message))
        self.render_clients(value); self.update_tray()

    def update_tray(self):
        self.spinner.set_visible(self.busy)
        self.switch_mode.set_sensitive(not self.busy)
        for name, action in self.actions.items():
            action.set_enabled(not self.busy and (name != 'password' or self.current.get('phase', 'off') == 'off'))
        self.actions['reveal-password'].set_enabled(not self.busy and not self.reveal_pending
                                                   and bool(self.current.get('configured')))
        tray = getattr(self.get_application(), 'tray', None)
        if tray is not None: tray.update(self.current, self.busy)

    def new_client_card(self, mac):
        group = Adw.PreferencesGroup()
        header = Adw.ActionRow(); header.set_use_markup(False); header.set_title_lines(1)
        header.add_prefix(Gtk.Image(icon_name='computer-symbolic'))
        group.add(header)
        values = {}
        for key, title in [('ipv4', _('IP address')), ('mac', _('MAC address')), ('signal', _('Signal strength')), ('time', _('Connected for'))]:
            row = Adw.ActionRow(title=title)
            label = Gtk.Label(selectable=key in ('ipv4', 'mac'), valign=Gtk.Align.CENTER)
            if key == 'time': label.set_wrap(True); label.set_max_width_chars(22)
            label.set_direction(text_direction() if key == 'time' else Gtk.TextDirection.LTR)
            if key in ('ipv4', 'mac'): label.add_css_class('monospace')
            row.add_suffix(label); group.add(row); values[key] = label
        copy = Gtk.Button(label=_('Copy IP address'), height_request=38)
        copy.add_css_class('flat'); copy.connect('clicked', lambda _: self.copy_ip(mac))
        group.add(copy); self.client_group.append(group)
        return {'row': header, 'card': group, 'values': values, 'copy': copy}

    def render_clients(self, value):
        records = {row['mac']: row for row in value.get('client_details', [])
                   if isinstance(row, dict) and mac_address(row.get('mac'))}
        for mac in set(self.client_rows) - set(records): self.client_group.remove(self.client_rows.pop(mac)['card'])
        for mac, record in records.items():
            if mac not in self.client_rows: self.client_rows[mac] = self.new_client_card(mac)
            widgets = self.client_rows[mac]
            name = hostname(record.get('hostname')) or _('Unknown')
            widgets['row'].set_title(name); widgets['row'].set_tooltip_text(name)
            ip, signal = ipv4_address(record.get('ipv4')), record.get('signal_dbm')
            fields = {'ipv4': ip or _('Unknown'), 'mac': mac,
                      'signal': str(signal) + ' dBm' if type(signal) is int else _('Unknown'),
                      'time': duration_label(record.get('connected_seconds'))}
            for key, label in widgets['values'].items(): label.set_label(fields[key])
            widgets['copy'].set_sensitive(ip is not None)
        unavailable = value.get('client_data_status') in ('STALE', 'UNAVAILABLE')
        self.empty_clients.set_title(_('Device list unavailable') if unavailable else _('No devices connected'))
        self.empty_clients.set_description(_('Try refreshing in a moment.') if unavailable else _('Devices connected to this hotspot will appear here.'))
        self.client_stack.set_visible_child_name('list' if records else 'empty')

    def copy_ip(self, mac):
        value = expire(dict(self.current))
        for row in value.get('client_details', []):
            if row.get('mac') == mac:
                address = ipv4_address(row.get('ipv4'))
                if address: self.get_clipboard().set(address)
                return

    def about(self):
        from . import __version__
        dialog = Adw.Dialog(title=_('About AAG Hotspot'), content_width=360)
        dialog.set_direction(text_direction())
        box = self.content_box()
        box.append(Gtk.Image(icon_name=icon_name('local'), pixel_size=48))
        box.append(Gtk.Label(label=_('AAG Hotspot')))
        box.append(Gtk.Label(label=_('Cellular Internet sharing and local Wi-Fi for Ubuntu'), wrap=True))
        box.append(Gtk.Label(label=_('Version')))
        version = Gtk.Label(label=__version__, selectable=True)
        version.set_direction(Gtk.TextDirection.LTR); box.append(version)
        close = Gtk.Button(label=_('Close')); close.connect('clicked', lambda _: dialog.close()); box.append(close)
        dialog.set_child(box)
        dialog.present(self)

    def refresh(self):
        if self.closed: return False
        if not self.busy and not self.refreshing:
            self.refreshing = True
            def done(value):
                self.refreshing = False
                if not self.busy: self.render(value)
                if self.get_application().settings.error:
                    self.notice.set_label(_('Your language preference could not be read or saved. Check your user settings directory.'))
                    self.notice.set_visible(True)
            self.dispatch(self.transport.status, done)
        return True

    def activate_mode(self, action):
        if self.busy: return
        if not self.current.get('installed', True):
            self.notice.set_label(error_message('INSTALLATION_REQUIRED'))
            self.notice.set_visible(True)
            return
        if action != 'off' and not self.current.get('configured'):
            self.password_dialog(after=action)
            return
        self.request(action)

    def request(self, action, password=None, after=None):
        self.clear_secret()
        self.busy = True
        if action in ('internet', 'local', 'off'):
            self.current.update(clients=None, client_count=None, client_details=[], client_data_status='UNAVAILABLE')
            self.render_clients(self.current)
        self.update_tray()
        self.spinner.start()
        for button in self.buttons.values(): button.set_sensitive(False)
        self.notice.set_label(_('Waiting for authorization and completion…')); self.notice.set_visible(True)
        def done(result):
            self.busy = False
            self.update_tray()
            self.spinner.stop()
            for button in self.buttons.values(): button.set_sensitive(True)
            if result.get('ok'):
                if result.get('status'): self.render(result['status'])
                if after: self.activate_mode(after)
                else: self.refresh()
            else:
                self.notice.set_label(error_message(result.get('error', 'REQUEST_FAILED'))); self.notice.set_visible(True)
        self.dispatch(lambda: self.transport.request(action, password), done)

    def clear_secret(self):
        self.reveal_generation += 1
        if self.secret_view is not None:
            self.secret_view.clear()
            self.secret_view.close()
            self.secret_view = None

    def reveal_password(self):
        if self.busy or self.reveal_pending or self.closed: return
        if self.secret_view is not None and not self.secret_view.cleared:
            self.secret_view.present(self)
            return
        self.reveal_pending = True
        generation = self.reveal_generation
        self.update_tray()
        # Dedicated delivery: consume and wipe the secret even if the window
        # closes during Polkit. Never hand secret replies to render/diagnostics.
        future = self.pool.submit(self.transport.reveal_password)
        def complete(f):
            try: result = f.result()
            except Exception: result = {'ok': False}
            secret = result.pop('secret', bytearray())
            authorized = result.get('ok') and bool(secret)
            auth_denied = result.get('error') == 'AUTHENTICATION_CANCELLED_OR_DENIED'
            def deliver():
                try:
                    self.reveal_pending = False
                    if self.closed or generation != self.reveal_generation: return False
                    self.update_tray()
                    if authorized:
                        self.secret_view = SecretDialog(secret, self.get_clipboard())
                        self.secret_view.present(self)
                    else:
                        self.notice.set_label(_('Authorization was cancelled or denied. Your hotspot was not changed.') if auth_denied
                                              else _('The stored password could not be read. Your hotspot was not changed.'))
                        self.notice.set_visible(True)
                finally:
                    secret[:] = b'\0' * len(secret)
                return False
            GLib.idle_add(deliver)
        future.add_done_callback(complete)

    def password_dialog(self, after=None):
        if self.busy: return
        if self.current.get('phase', 'off') != 'off':
            self.notice.set_label(_('Turn off the hotspot before changing its password.'))
            self.notice.set_visible(True)
            return
        dialog = Adw.Dialog(title=_('Hotspot password'), content_width=380)
        dialog.set_direction(text_direction())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for key in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_' + key)(24)
        box.append(Gtk.Label(label=_('Use 12–63 ASCII letters, numbers or symbols.'), wrap=True))
        first = Gtk.Entry(buffer=Gtk.PasswordEntryBuffer(), visibility=False,
                          input_purpose=Gtk.InputPurpose.PASSWORD, placeholder_text=_('New password'))
        second = Gtk.Entry(buffer=Gtk.PasswordEntryBuffer(), visibility=False,
                           input_purpose=Gtk.InputPurpose.PASSWORD, placeholder_text=_('Confirm password'))
        for field in (first, second):
            field.set_direction(Gtk.TextDirection.LTR)
            box.append(field)
        peek = Gtk.CheckButton(label=_('Show password'))
        peek.connect('toggled', lambda button: (first.set_visibility(button.get_active()), second.set_visibility(button.get_active())))
        box.append(peek)
        error = Gtk.Label(wrap=True)
        box.append(error)
        save = Gtk.Button(label=_('Save'), height_request=48)
        save.add_css_class('suggested-action')
        def submit(_button):
            password = first.get_text()
            if password != second.get_text():
                error.set_label(_('The passwords do not match.'))
                return
            try: validate_password(password)
            except ValueError:
                error.set_label(_('Enter 12–63 printable ASCII characters.'))
                return
            first.set_text('')
            second.set_text('')
            dialog.close()
            self.request('configure', password, after)
        save.connect('clicked', submit)
        box.append(save)
        dialog.set_child(box)
        dialog.connect('closed', lambda _: (first.set_text(''), second.set_text('')))
        dialog.present(self)

    def diagnose(self):
        if self.busy: return
        def done(value):
            checks = value.get('checks', {})
            lines = []
            for key, label in [('helper_installed', _('Application installation')), ('password_configured', _('Hotspot password')),
                               ('uplink_supported', _('Internet source'))]:
                lines.append(_('{label}: {result}').format(label=label, result=_('OK') if checks.get(key) else _('Needs attention')))
            if any(checks.get(x) is False for x in ('nmcli', 'iw', 'ip', 'nft', 'dnsmasq', 'pkexec')):
                lines.append(_('Required system components are missing.'))
            lines.append(_('Wi-Fi STA+AP uplink sharing is not yet supported.'))
            dialog = Adw.AlertDialog(heading=_('Diagnostics'), body='\n'.join(lines))
            dialog.set_direction(text_direction())
            dialog.add_response('close', _('Close'))
            dialog.present(self)
        self.dispatch(self.transport.doctor, done)


class Application(Adw.Application):
    def __init__(self, transport=client, settings=None):
        super().__init__(application_id='org.aag.Hotspot', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.settings = settings or i18n.LanguageSettings(
            Path(GLib.get_user_config_dir()) / 'aag-hotspot' if transport is client else None)
        i18n.set_language(self.settings.language)
        self.transport = transport
        self.tray = None
        self.exiting = False
    def do_activate(self):
        window = self.get_active_window()
        if window is None and self.get_windows(): window = self.get_windows()[0]
        if window is None: window = Window(self, self.transport)
        if self.tray is None and self.transport is client:
            from .tray import Indicator
            try:
                self.tray = Indicator(self.tray_action)
                self.tray.update(window.current)
            except GLib.Error:
                window.notice.set_label(_('The tray indicator is unavailable. You can use the main window.'))
                window.notice.set_visible(True)
        window.present()

    def tray_action(self, action):
        if action == 'quit':
            self.exiting = True
            for window in self.get_windows(): window.dispose_view(); window.close()
            self.quit()
            return
        window = self.get_active_window()
        if window is None:
            windows = self.get_windows()
            window = windows[0] if windows else Window(self, self.transport)
        if action == 'refresh': window.refresh(); return
        window.present()
        if action == 'clients': window.show_clients()
        elif action in ('internet', 'local', 'off'): window.activate_mode(action)

    def do_shutdown(self):
        if self.tray is not None: self.tray.close()
        for window in self.get_windows(): window.dispose_view()
        Adw.Application.do_shutdown(self)


def main(argv=None):
    if os.geteuid() == 0: raise SystemExit('The GUI must run as the desktop user, never as root.')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return Application().run(argv)
