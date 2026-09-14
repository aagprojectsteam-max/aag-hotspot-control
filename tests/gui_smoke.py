#!/usr/bin/python3
"""Real GTK widgets with an in-memory transport; no helper or network mutation."""
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from aag_hotspot.gui import Application, Window, presentation, Gtk, GLib


class Transport:
    def __init__(self):
        self.calls = []
        self.value = {'mode': 'off', 'phase': 'off', 'ssid': 'AAG-Hotspot', 'uplink': 'wwan0',
                      'clients': 0, 'configured': True, 'installed': True, 'error': None}
    def status(self): return dict(self.value)
    def doctor(self): return {'physical_client_validation': 'NOT_TESTED'}
    def request(self, action, password=None):
        self.calls.append(action)
        self.value.update(mode=action, phase='off' if action == 'off' else 'active')
        return {'ok': True, 'status': dict(self.value)}


def main():
    if os.geteuid() == 0: raise RuntimeError('GUI validation must not be root')
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
    t = Transport(); app = Application(t)
    app.set_application_id('org.aag.Hotspot.SmokeTest')
    app.register(None)
    if app.get_is_remote(): raise RuntimeError('Smoke test already running')
    window = Window(app, t)
    window.present()
    actions = ['internet', 'local', 'off']
    checks = {}; done = False; step = 0; sent = False
    started = time.monotonic()
    def advance():
        nonlocal step, sent, done
        if time.monotonic() - started > 15:
            checks['timeout'] = False; done = True; return False
        if window.busy or window.refreshing: return True
        if step < len(actions):
            action = actions[step]
            if not sent:
                window.buttons[action].emit('clicked'); sent = True; return True
            checks[action + '_button_dispatch'] = t.calls[-1] == action
            checks[action + '_mode_text'] = window.mode.get_label() == presentation(t.value)['mode']
            step += 1;sent = False;return True
        checks['rtl_window'] = window.get_direction() == Gtk.TextDirection.RTL
        checks['rtl_buttons'] = all(b.get_direction() == Gtk.TextDirection.RTL for b in window.buttons.values())
        checks['all_main_buttons'] = [window.buttons[x].get_label() for x in actions] == ['הפעל עם אינטרנט', 'הפעל מקומי בלבד', 'כבה Hotspot']
        checks['touch_targets'] = all(b.get_size_request().height >= 44 for b in window.buttons.values())
        checks['source_cellular'] = window.values['source'].get_label() == 'FM350 / סלולרי'
        checks['unknown_count_not_zero'] = presentation({'clients': None})['clients'] == 'לא ידוע'
        checks['wifi_unvalidated_label'] = presentation({'uplink': 'wlan0'})['source'] == 'Wi-Fi (UNVALIDATED)'
        checks['non_root'] = os.geteuid() != 0
        if len(sys.argv) == 2:
            try:
                paintable = Gtk.WidgetPaintable.new(window)
                snapshot = Gtk.Snapshot.new()
                paintable.snapshot(snapshot, float(window.get_width()), float(window.get_height()))
                node = snapshot.to_node()
                texture = window.get_renderer().render_texture(node, None)
                checks['screenshot_saved'] = texture.save_to_png(sys.argv[1])
            except Exception as exc:
                checks['screenshot_note'] = type(exc).__name__
        done = True
        return False
    GLib.timeout_add(150, advance)
    while not done and time.monotonic() - started < 18:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.01)
    if not done: checks['timeout'] = False
    window.close()
    result = {'checks': checks, 'actions': t.calls, 'network_transport': 'IN_MEMORY_ONLY',
              'physical_client_validation': 'NOT_TESTED', 'passed': all(v is not False for v in checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
