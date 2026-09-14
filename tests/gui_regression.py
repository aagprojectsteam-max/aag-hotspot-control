#!/usr/bin/python3
"""Real unprivileged GTK widgets; all backend actions are explicit fixtures."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from aag_hotspot import gui


class Transport:
    def __init__(self):
        self.calls = []
        self.error = None
        self.value = {'mode': 'off', 'phase': 'off', 'health': 'OK', 'ssid': 'AAG-Hotspot',
                      'uplink': 'wwan0', 'clients': 0, 'configured': True, 'installed': True}

    def status(self): return dict(self.value)

    def request(self, action, password=None):
        self.calls.append(action)
        if self.error: return {'ok': False, 'error': self.error}
        self.value.update(mode=action, phase='off' if action == 'off' else 'active')
        return {'ok': True, 'status': dict(self.value)}


def main():
    if os.geteuid() == 0: raise SystemExit('GUI tests must be unprivileged')
    gui.Gtk.Widget.set_default_direction(gui.Gtk.TextDirection.RTL)
    t = Transport()
    app = gui.Application(t)
    app.set_application_id('org.aag.Hotspot.Regression')
    app.register(None)
    if app.get_is_remote(): raise SystemExit('A regression window is already running')
    window = gui.Window(app, t)
    window.present()
    checks = {}

    def settle():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            while gui.GLib.MainContext.default().pending(): gui.GLib.MainContext.default().iteration(False)
            if not window.busy and not window.refreshing and window.get_mapped(): return
            time.sleep(0.02)
        raise RuntimeError('GUI fixture did not settle')

    def forbidden(*args, **kwargs): raise AssertionError('No helper/process permitted in GUI fixture')
    try:
        with patch('subprocess.run', forbidden), patch('subprocess.Popen', forbidden):
            settle()
            for action, label in [('internet', 'Hotspot + אינטרנט'), ('local', 'מקומי בלבד'), ('off', 'הנקודה החמה כבויה')]:
                window.buttons[action].emit('clicked')
                settle()
                checks[action + '_button_state'] = t.calls[-1] == action and window.mode.get_label() == label
            for error in ('NM_DEVICE_RFKILL_BLOCKED', 'NM_DEVICE_READINESS_TIMEOUT', 'NM_READINESS_UNAVAILABLE',
                          'HELPER_UNAVAILABLE', 'TIMEOUT_RECOVERY_PENDING', 'CELLULAR_REQUIRED'):
                t.error = error
                window.buttons['internet'].emit('clicked')
                settle()
                checks[error] = (window.notice.get_label() == gui.error_message(error)
                                 and window.current['mode'] == 'off' and not window.busy
                                 and all(b.get_sensitive() for b in window.buttons.values()))
            t.value.update(mode='internet', phase='active', health='UNKNOWN', error='STALE_STATUS', clients=3)
            window.refresh()
            settle()
            checks['stale_not_shown_active'] = window.mode.get_label() == 'לא ניתן לאמת את מצב הרשת'
            checks['stale_count_unknown'] = window.values['clients'].get_label() == 'לא ידוע'
            checks['hebrew_rtl'] = window.get_direction() == gui.Gtk.TextDirection.RTL
            checks['unprivileged'] = os.geteuid() != 0
            checks['all_buttons'] = set(window.buttons) == {'internet', 'local', 'off'}
    finally:
        window.close()
        while gui.GLib.MainContext.default().pending(): gui.GLib.MainContext.default().iteration(False)
    result = {'checks': checks, 'passed': all(checks.values()), 'uid': os.geteuid(),
              'network_transport': 'IN_MEMORY_ONLY', 'physical_client_validation': 'NOT_TESTED'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
