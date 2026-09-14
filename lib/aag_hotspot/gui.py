"""Native Hebrew GNOME views; the existing client transport owns all state."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Pango
from . import client
from .policy import validate_password
from .clients import expire, hostname, ipv4_address, mac_address
from .ui_support import Geometry, DEFAULT_SIZE, MIN_SIZE, duration_label, icon_directory, icon_name


def presentation(value):
    modes = {'off': 'הנקודה החמה כבויה', 'local': 'מקומי בלבד', 'internet': 'Hotspot + אינטרנט'}
    state = modes.get(value.get('mode'), 'מצב לא ידוע')
    if value.get('phase') in ('starting', 'switching'): state = 'מעדכן את הרשת…'
    if value.get('phase') == 'stopping': state = 'מכבה את הרשת…'
    uplink = value.get('uplink')
    source = 'FM350 / סלולרי' if uplink == 'wwan0' else ('Wi-Fi (UNVALIDATED)' if uplink and uplink.startswith(('wl', 'wifi')) else 'אין חיבור')
    count = value.get('clients')
    if value.get('health') in ('UNKNOWN', 'ERROR', 'NOT_INSTALLED'):
        state, count = 'לא ניתן לאמת את מצב הרשת', None
    return {'mode': state, 'ssid': value.get('ssid', 'AAG-Hotspot'), 'source': source,
            'clients': str(count) if type(count) is int and count >= 0 else 'לא ידוע'}


def error_message(error):
    if not error: return ''
    if 'INSTALLATION_REQUIRED' in error: return 'האפליקציה מוכנה להתקנה. יש להשלים התקנה לפני הפעלת הרשת.'
    if 'AUTHENTICATION' in error: return 'האימות בוטל או לא אושר. מצב הרשת לא שונה על ידי בקשה זו.'
    if 'WIFI_STA_UNVALIDATED' in error: return 'חיבור ה־Wi-Fi הקיים נשמר. שימוש בו כמקור אינטרנט עדיין אינו זמין.'
    if 'CELLULAR_REQUIRED' in error: return 'נדרש חיבור סלולרי פעיל כמקור האינטרנט. אפשר לבחור רשת מקומית בלבד.'
    if 'CONFIGURATION_REQUIRED' in error: return 'יש להגדיר סיסמה לרשת תחילה.'
    if 'RFKILL' in error or 'hardware radio is blocked' in error: return 'מתאם ה־Wi-Fi חסום. יש לבדוק את מתג האלחוט או מצב הטיסה.'
    if 'READINESS_TIMEOUT' in error: return 'מתאם ה־Wi-Fi לא היה מוכן בזמן. יש לבדוק את מצב הרשת לפני ניסיון נוסף.'
    if 'NM_READINESS_UNAVAILABLE' in error: return 'לא ניתן לקבל מצב מ־NetworkManager. יש לבדוק ששירות הרשת פועל.'
    if 'TIMEOUT' in error: return 'הפעולה חרגה מהזמן. ייתכן שהניקוי עדיין מתבצע; יש לבדוק מצב ולבקש כיבוי.'
    if 'HELPER_' in error: return 'לא ניתן לקבל תשובה תקינה משירות האפליקציה. יש לבדוק את ההתקנה.'
    if 'BUSY' in error: return 'פעולה אחרת מתבצעת. יש להמתין ולרענן.'
    if 'STALE' in error or 'UNREADABLE' in error: return 'לא ניתן לאמת את מצב הרשת כרגע. יש לרענן או להפעיל בדיקה.'
    return 'הפעולה לא הושלמה. פרטי האבחון זמינים בתפריט אבחון; אין להניח שהרשת פעילה.'


class Window(Adw.ApplicationWindow):
    def __init__(self, app, transport=client, geometry=None):
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
        self.geometry = geometry or (Geometry(Path(GLib.get_user_config_dir()) / 'aag-hotspot/window.json') if transport is client else None)
        size = self.geometry.load() if self.geometry else dict(width=DEFAULT_SIZE[0], height=DEFAULT_SIZE[1], maximized=False)
        super().__init__(application=app, title='AAG Hotspot', default_width=size['width'], default_height=size['height'])
        self.set_size_request(*MIN_SIZE)
        if size['maximized']: self.maximize()
        self.transport, self.pool = transport, ThreadPoolExecutor(max_workers=1)
        self.busy, self.refreshing, self.closed = False, False, False
        self.current = {'configured': False}
        self.connect('close-request', self.on_close)
        self.set_direction(Gtk.TextDirection.RTL)
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(str(icon_directory()))
        self.navigation = Adw.NavigationView()
        self.actions = {}
        callbacks = {'refresh': self.refresh, 'password': self.password_dialog, 'diagnose': self.diagnose,
                     'about': self.about, 'clients': self.show_clients,
                     'mode-internet': lambda: self.activate_mode('internet'),
                     'mode-local': lambda: self.activate_mode('local'),
                     'quit': lambda: app.tray_action('quit') if hasattr(app, 'tray_action') else self.close()}
        for name, callback in callbacks.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=callback: fn())
            self.add_action(action); self.actions[name] = action
        self.menu_model = Gio.Menu()
        self.menu_model.append('סיסמת הרשת…', 'win.password')
        self.menu_model.append('אבחון', 'win.diagnose')
        self.menu_model.append('רענן', 'win.refresh')
        extra = Gio.Menu(); extra.append('אודות AAG Hotspot', 'win.about'); extra.append('סגור את האפליקציה', 'win.quit')
        self.menu_model.append_section(None, extra)
        self.main_page = self.build_main()
        self.devices_page = self.build_devices()
        self.navigation.add(self.main_page)
        self.navigation.add(self.devices_page)
        self.set_content(self.navigation)
        self.timer = GLib.timeout_add_seconds(5, self.refresh)
        self.refresh()

    def header(self, title, refresh=False):
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title))
        menu = Gtk.MenuButton(icon_name='open-menu-symbolic', tooltip_text='תפריט')
        menu.set_menu_model(self.menu_model)
        header.pack_end(menu)
        if refresh:
            button = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='רענן')
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
        toolbar = Adw.ToolbarView(); toolbar.add_top_bar(self.header('AAG Hotspot'))
        content = self.content_box()
        summary = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.status_icon = Gtk.Image(icon_name=icon_name('off'), pixel_size=36, valign=Gtk.Align.START)
        summary.append(self.status_icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        self.mode = Gtk.Label(label='טוען…', wrap=True, xalign=0)
        self.mode.add_css_class('title-2')
        self.description = Gtk.Label(wrap=True, xalign=0)
        self.description.add_css_class('dim-label')
        text.append(self.mode); text.append(self.description); summary.append(text); content.append(summary)
        self.info_group = Adw.PreferencesGroup()
        self.values, self.info_rows = {}, {}
        for key, title in [('ssid', 'שם הרשת'), ('source', 'מקור אינטרנט'), ('clients', 'מכשירים מחוברים')]:
            row = Adw.ActionRow(title=title)
            value = Gtk.Label(label='—', selectable=key=='ssid', valign=Gtk.Align.CENTER)
            value.set_direction(Gtk.TextDirection.LTR if key in ('ssid', 'clients') else Gtk.TextDirection.RTL)
            row.add_suffix(value)
            if key == 'clients':
                row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
                row.set_activatable(True)
                row.connect('activated', lambda _: self.show_clients())
            self.values[key], self.info_rows[key] = value, row
            self.info_group.add(row)
        content.append(self.info_group)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.buttons = {}
        for action, label, style in [('internet', 'הפעל עם אינטרנט', 'suggested-action'),
                                     ('local', 'הפעל מקומי בלבד', ''), ('off', 'כבה Hotspot', 'destructive-action')]:
            button = Gtk.Button(label=label, height_request=44, visible=False)
            if style: button.add_css_class(style)
            button.connect('clicked', lambda _, name=action: self.activate_mode(name))
            self.buttons[action] = button; controls.append(button)
        self.switch_mode = Gtk.MenuButton(label='החלף מצב', halign=Gtk.Align.CENTER, visible=False)
        self.switch_mode.add_css_class('flat'); controls.append(self.switch_mode)
        content.append(controls)
        self.notice = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.notice.add_css_class('dim-label'); content.append(self.notice)
        self.main_scroll = self.scroll_content(content)
        toolbar.set_content(self.main_scroll)
        return Adw.NavigationPage.new(toolbar, 'AAG Hotspot')

    def build_devices(self):
        toolbar = Adw.ToolbarView(); toolbar.add_top_bar(self.header('מכשירים מחוברים', refresh=True))
        self.client_stack = Gtk.Stack(vhomogeneous=False, hhomogeneous=False)
        self.empty_clients = Adw.StatusPage(title='אין מכשירים מחוברים כרגע',
                                          description='מכשירים המחוברים לרשת יופיעו כאן.', icon_name='computer-symbolic')
        self.empty_clients.add_css_class('compact')
        self.client_stack.add_named(self.empty_clients, 'empty')
        self.client_group = self.content_box(); self.client_rows = {}
        self.devices_scroll = self.scroll_content(self.client_group)
        self.client_stack.add_named(self.devices_scroll, 'list')
        toolbar.set_content(self.client_stack)
        return Adw.NavigationPage.new(toolbar, 'מכשירים מחוברים')

    def show_clients(self):
        if self.navigation.get_visible_page() is not self.devices_page: self.navigation.push(self.devices_page)
        self.refresh()

    def save_geometry(self):
        if self.geometry:
            width, height = self.get_default_size()
            self.geometry.save(width, height, self.is_maximized())

    def on_close(self, *_):
        self.save_geometry()
        app = self.get_application()
        if getattr(app, 'tray', None) is not None and app.tray.registered and not getattr(app, 'exiting', False):
            self.set_visible(False)
            return True
        self.dispose_view()
        return False

    def dispose_view(self):
        if self.closed: return
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
        self.description.set_label({'off': 'בחרו כיצד להפעיל את הרשת.',
                                    'internet': 'גישה לאינטרנט דרך החיבור הסלולרי.',
                                    'local': 'חיבור מקומי, ללא שיתוף אינטרנט.'}.get(mode, ''))
        self.status_icon.set_from_icon_name(icon_name(mode))
        if mode == 'internet' and active: self.status_icon.add_css_class('accent')
        else: self.status_icon.remove_css_class('accent')
        for key, label in self.values.items(): label.set_label(view[key])
        self.info_rows['source'].set_visible(not off)
        self.info_rows['source'].set_title('אינטרנט משותף' if mode == 'local' else 'מקור אינטרנט')
        if mode == 'local': self.values['source'].set_label('לא')
        for action, button in self.buttons.items():
            button.set_visible((action in ('internet', 'local')) if off else action == 'off')
            button.set_sensitive(not self.busy)
        switch = Gio.Menu()
        alternate = 'local' if mode == 'internet' else 'internet'
        switch.append('מקומי בלבד' if alternate == 'local' else 'Hotspot + אינטרנט', 'win.mode-' + alternate)
        self.switch_mode.set_menu_model(switch); self.switch_mode.set_visible(active)
        message = error_message(value.get('error')); self.notice.set_label(message); self.notice.set_visible(bool(message))
        self.render_clients(value); self.update_tray()

    def update_tray(self):
        self.spinner.set_visible(self.busy)
        self.switch_mode.set_sensitive(not self.busy)
        for name, action in self.actions.items():
            action.set_enabled(not self.busy and (name != 'password' or self.current.get('phase', 'off') == 'off'))
        tray = getattr(self.get_application(), 'tray', None)
        if tray is not None: tray.update(self.current, self.busy)

    def new_client_card(self, mac):
        group = Adw.PreferencesGroup()
        header = Adw.ActionRow(); header.set_use_markup(False); header.set_title_lines(1)
        header.add_prefix(Gtk.Image(icon_name='computer-symbolic'))
        group.add(header)
        values = {}
        for key, title in [('ipv4', 'כתובת IP'), ('mac', 'כתובת MAC'), ('signal', 'עוצמת קליטה'), ('time', 'זמן חיבור')]:
            row = Adw.ActionRow(title=title)
            label = Gtk.Label(selectable=key in ('ipv4', 'mac'), valign=Gtk.Align.CENTER)
            label.set_direction(Gtk.TextDirection.RTL if key == 'time' else Gtk.TextDirection.LTR)
            if key in ('ipv4', 'mac'): label.add_css_class('monospace')
            row.add_suffix(label); group.add(row); values[key] = label
        copy = Gtk.Button(label='העתק כתובת IP', height_request=38)
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
            name = hostname(record.get('hostname')) or 'לא ידוע'
            widgets['row'].set_title(name); widgets['row'].set_tooltip_text(name)
            ip, signal = ipv4_address(record.get('ipv4')), record.get('signal_dbm')
            fields = {'ipv4': ip or 'לא ידוע', 'mac': mac,
                      'signal': str(signal) + ' dBm' if type(signal) is int else 'לא ידוע',
                      'time': duration_label(record.get('connected_seconds'))}
            for key, label in widgets['values'].items(): label.set_label(fields[key])
            widgets['copy'].set_sensitive(ip is not None)
        unavailable = value.get('client_data_status') in ('STALE', 'UNAVAILABLE')
        self.empty_clients.set_title('לא ניתן לעדכן את רשימת המכשירים' if unavailable else 'אין מכשירים מחוברים כרגע')
        self.empty_clients.set_description('נסו לרענן בעוד רגע.' if unavailable else 'מכשירים המחוברים לרשת יופיעו כאן.')
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
        dialog = Adw.AboutDialog(application_name='AAG Hotspot', application_icon=icon_name('local'),
                                 version=__version__, comments='נקודה חמה סלולרית ורשת מקומית ל־Ubuntu')
        dialog.present(self)

    def refresh(self):
        if self.closed: return False
        if not self.busy and not self.refreshing:
            self.refreshing = True
            def done(value):
                self.refreshing = False
                if not self.busy: self.render(value)
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
        self.busy = True
        if action in ('internet', 'local', 'off'):
            self.current.update(clients=None, client_count=None, client_details=[], client_data_status='UNAVAILABLE')
            self.render_clients(self.current)
        self.update_tray()
        self.spinner.start()
        for button in self.buttons.values(): button.set_sensitive(False)
        self.notice.set_label('ממתין לאישור ולסיום הפעולה…'); self.notice.set_visible(True)
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

    def password_dialog(self, after=None):
        if self.busy: return
        if self.current.get('phase', 'off') != 'off':
            self.notice.set_label('יש לכבות את הרשת לפני שינוי הסיסמה.')
            self.notice.set_visible(True)
            return
        dialog = Adw.Dialog(title='סיסמת הרשת', content_width=380)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for key in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_' + key)(24)
        box.append(Gtk.Label(label='בחרו 12–63 תווים באנגלית, מספרים או סימנים.', wrap=True))
        first = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text='סיסמה חדשה')
        second = Gtk.PasswordEntry(placeholder_text='הקלידו שוב')
        for field in (first, second):
            field.set_direction(Gtk.TextDirection.LTR)
            box.append(field)
        error = Gtk.Label(wrap=True)
        box.append(error)
        save = Gtk.Button(label='שמירה', height_request=48)
        save.add_css_class('suggested-action')
        def submit(_):
            password = first.get_text()
            if password != second.get_text():
                error.set_label('הסיסמאות אינן תואמות.')
                return
            try: validate_password(password)
            except ValueError:
                error.set_label('יש לבחור 12–63 תווי ASCII ניתנים להדפסה.')
                return
            first.set_text('')
            second.set_text('')
            dialog.close()
            self.request('configure', password, after)
        save.connect('clicked', submit)
        box.append(save)
        dialog.set_child(box)
        dialog.present(self)

    def diagnose(self):
        if self.busy: return
        def done(value):
            checks = value.get('checks', {})
            lines = []
            for key, label in [('helper_installed', 'התקנת האפליקציה'), ('password_configured', 'סיסמת הרשת'),
                               ('cellular_public_route', 'מקור אינטרנט סלולרי')]:
                lines.append(label + ': ' + ('תקין' if checks.get(key) else 'נדרשת בדיקה'))
            if any(checks.get(x) is False for x in ('nmcli', 'iw', 'ip', 'nft', 'dnsmasq', 'pkexec')):
                lines.append('חסרים רכיבי מערכת הדרושים להפעלה.')
            lines.append('מצב Wi-Fi כמקור אינטרנט עדיין אינו זמין.')
            dialog = Adw.AlertDialog(heading='אבחון', body='\n'.join(lines))
            dialog.add_response('close', 'סגירה')
            dialog.present(self)
        self.dispatch(self.transport.doctor, done)


class Application(Adw.Application):
    def __init__(self, transport=client):
        super().__init__(application_id='org.aag.Hotspot', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
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
                window.notice.set_label('מחוון המגש אינו זמין. אפשר להשתמש בחלון הראשי.')
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
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
    return Application().run(argv)
