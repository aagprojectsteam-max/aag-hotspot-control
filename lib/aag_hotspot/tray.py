"""Unprivileged GTK4-compatible StatusNotifierItem and DBusMenu.

Uses the existing session tray host; installs no extension/autostart/dependency.
Only explicit menu clicks invoke the GUI's existing polkit action transport.
"""
from gi.repository import Gio, GLib
from .ui_support import icon_directory, icon_name

ITEM = 'org.kde.StatusNotifierItem'
MENU = 'com.canonical.dbusmenu'
PATH = '/StatusNotifierItem'
MENU_PATH = PATH + '/Menu'
WATCHER = 'org.kde.StatusNotifierWatcher'

ITEM_XML = '''<node><interface name="org.kde.StatusNotifierItem">
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="WindowId" type="i" access="read"/><property name="IconName" type="s" access="read"/>
<property name="IconThemePath" type="s" access="read"/><property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="OverlayIconName" type="s" access="read"/><property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionIconName" type="s" access="read"/><property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionMovieName" type="s" access="read"/><property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
<property name="XAyatanaLabel" type="s" access="read"/><property name="XAyatanaLabelGuide" type="s" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<signal name="NewTitle"/><signal name="NewIcon"/><signal name="NewToolTip"/>
<signal name="NewStatus"><arg type="s"/></signal>
<signal name="XAyatanaNewLabel"><arg type="s"/><arg type="s"/></signal>
</interface></node>'''

MENU_XML = '''<node><interface name="com.canonical.dbusmenu">
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
<arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
</interface></node>'''


def count_label(count):
    if type(count) is not int or count < 0: return 'מספר מכשירים לא ידוע'
    if count == 1: return '1 מכשיר מחובר'
    return str(count) + ' מכשירים מחוברים'


def model(value, busy=False):
    mode = {'off': 'כבוי', 'internet': 'אינטרנט', 'local': 'מקומי בלבד'}.get(value.get('mode'), 'מצב לא ידוע')
    if value.get('health') not in (None, 'OK'): mode = 'מצב לא ידוע'
    if busy or value.get('phase') in ('starting', 'switching', 'stopping'): mode = 'מעדכן את הרשת…'
    count = value.get('clients') if value.get('health') in (None, 'OK') else None
    title = 'AAG Hotspot — ' + mode
    if value.get('mode') != 'off': title += ' — ' + count_label(count)
    rows = [(6, 'פתח AAG Hotspot', 'open'), (10, '', None),
            (1, 'מצב: ' + mode, None), (5, count_label(count), None)]
    if value.get('mode') in ('internet', 'local'):
        rows.extend([(11, '', None), (4, 'כבה Hotspot', 'off')])
    return {'title': title, 'rows': rows, 'busy': busy, 'icon': icon_name(value.get('mode'))}


class Indicator:
    def __init__(self, action, bus=None):
        self.action, self.registered, self.closed = action, False, False
        self.value, self.revision = model({'mode': 'off', 'clients': 0}), 1
        self.bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.ids = []
        for path, xml in ((PATH, ITEM_XML), (MENU_PATH, MENU_XML)):
            interface = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
            self.ids.append(self.bus.register_object(path, interface, self.method, self.property, None))
        self.watch = Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                     self.appeared, self.vanished)

    def appeared(self, *_):
        def registered(bus, result):
            try: bus.call_finish(result); self.registered = not self.closed
            except GLib.Error: self.registered = False
        self.bus.call(WATCHER, '/StatusNotifierWatcher', WATCHER, 'RegisterStatusNotifierItem',
                      GLib.Variant('(s)', (PATH,)), None, Gio.DBusCallFlags.NONE, 3000, None, registered)

    def vanished(self, *_): self.registered = False

    def update(self, value, busy=False):
        new = model(value, busy)
        if new == self.value or self.closed: return
        self.value = new; self.revision += 1
        for signal in ('NewTitle', 'NewIcon', 'NewToolTip'):
            self.bus.emit_signal(None, PATH, ITEM, signal, None)
        # Explicitly clear old indicator labels; top bar is icon-only.
        self.bus.emit_signal(None, PATH, ITEM, 'XAyatanaNewLabel', GLib.Variant('(ss)', ('', '')))
        properties = {key: self.property(None, None, PATH, ITEM, key) for key in ('Title', 'XAyatanaLabel', 'IconName', 'ToolTip')}
        self.bus.emit_signal(None, PATH, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                             GLib.Variant('(sa{sv}as)', (ITEM, properties, [])))
        self.bus.emit_signal(None, MENU_PATH, MENU, 'LayoutUpdated', GLib.Variant('(ui)', (self.revision, 0)))

    def property(self, connection, sender, path, interface, name):
        if interface == MENU:
            values = {'Version': ('u', 3), 'TextDirection': ('s', 'rtl'), 'Status': ('s', 'normal'), 'IconThemePath': ('as', [])}
        else:
            icon = self.value['icon']
            values = {key: ('s', '') for key in ('IconThemePath', 'OverlayIconName', 'AttentionIconName', 'AttentionMovieName', 'XAyatanaLabelGuide')}
            values.update({key: ('a(iiay)', []) for key in ('IconPixmap', 'OverlayIconPixmap', 'AttentionIconPixmap')})
            values.update(Category=('s', 'SystemServices'), Id=('s', 'aag-hotspot'), Title=('s', self.value['title']),
                          Status=('s', 'Active'), WindowId=('i', 0), IconName=('s', icon), ItemIsMenu=('b', False),
                          Menu=('o', MENU_PATH), ToolTip=('(sa(iiay)ss)', (icon, [], 'AAG Hotspot', self.value['title'])),
                          IconThemePath=('s', str(icon_directory())), XAyatanaLabel=('s', ''))
        pair = values.get(name)
        return GLib.Variant(*pair) if pair else None

    def properties(self, identifier, names=()):
        if identifier == 0: properties = {'children-display': GLib.Variant('s', 'submenu')}
        else:
            row = next((r for r in self.value['rows'] if r[0] == identifier), None)
            if row is None: raise ValueError('UNKNOWN_MENU_ITEM')
            if identifier in (10, 11): return {'type': GLib.Variant('s', 'separator')}
            enabled = row[2] is not None and not (self.value['busy'] and row[2] in ('internet', 'local', 'off'))
            properties = {'label': GLib.Variant('s', row[1]), 'enabled': GLib.Variant('b', enabled), 'visible': GLib.Variant('b', True)}
        return {key: value for key, value in properties.items() if not names or key in names}

    def layout(self, identifier, depth, names):
        children = []
        if identifier == 0 and depth != 0:
            children = [GLib.Variant('(ia{sv}av)', (r[0], self.properties(r[0], names), [])) for r in self.value['rows']]
        return (identifier, self.properties(identifier, names), children)

    def event(self, identifier, event):
        row = next((r for r in self.value['rows'] if r[0] == identifier), None)
        if row is None: return False
        if event == 'clicked' and row[2] and self.properties(identifier)['enabled'].unpack():
            def dispatch(): self.action(row[2]); return False
            GLib.idle_add(dispatch)
        return True

    def method(self, connection, sender, path, interface, method, args, invocation):
        values = args.unpack()
        try:
            result = None
            if interface == ITEM:
                if method in ('Activate', 'SecondaryActivate', 'ContextMenu'): self.action('open')
            elif method == 'GetLayout': result = GLib.Variant('(u(ia{sv}av))', (self.revision, self.layout(*values)))
            elif method == 'GetGroupProperties':
                result = GLib.Variant('(a(ia{sv}))', ([(i, self.properties(i, values[1])) for i in values[0]],))
            elif method == 'GetProperty': result = GLib.Variant('(v)', (self.properties(values[0])[values[1]],))
            elif method == 'Event': self.event(values[0], values[1])
            elif method == 'EventGroup': result = GLib.Variant('(ai)', ([row[0] for row in values[0] if not self.event(row[0], row[1])],))
            elif method == 'AboutToShow': self.action('refresh'); result = GLib.Variant('(b)', (False,))
            elif method == 'AboutToShowGroup': self.action('refresh'); result = GLib.Variant('(aiai)', ([], []))
            invocation.return_value(result)
        except (ValueError, KeyError, TypeError): invocation.return_dbus_error('org.aag.Hotspot.InvalidMenuRequest', 'Invalid menu request')

    def close(self):
        if self.closed: return
        self.closed = True; self.registered = False
        Gio.bus_unwatch_name(self.watch)
        for identifier in self.ids: self.bus.unregister_object(identifier)
