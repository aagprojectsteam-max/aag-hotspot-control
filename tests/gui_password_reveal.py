#!/usr/bin/python3
"""Real GTK + clipboard with synthetic credentials; no helper/network actions."""
import json
import os
from pathlib import Path
import sys
import time
from concurrent.futures import Future
from unittest.mock import patch
sys.path.insert(0, '/usr/lib/aag-hotspot' if '--installed' in sys.argv else str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot.gui import Application, Window, Gtk, GLib
from aag_hotspot import secret_dialog
SECRET = 'synthetic-test-password'


def pump(until=lambda: False, seconds=3):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        if until(): return True
        time.sleep(.01)
    return bool(until())


class Transport:
    def __init__(self): self.calls=[]; self.fail=None; self.mode='off'; self.last=None
    def status(self):
        return dict(mode=self.mode, phase='off' if self.mode=='off' else 'active', health='OK',
                    ssid='AAG-Hotspot', configured=True, installed=True, clients=0, uplink='wwan0')
    def reveal_password(self):
        self.calls.append('reveal')
        if self.fail: return dict(ok=False,error=self.fail)
        self.last=bytearray(SECRET.encode())
        return dict(ok=True,secret=self.last)
    def request(self,*args): raise AssertionError('Network action forbidden')


def main():
    assert os.geteuid()!=0
    t=Transport();app=Application(t);app.set_application_id('org.aag.Hotspot.PasswordTest');app.register(None)
    w=Window(app,t);w.present();checks={}
    try:
        assert pump(lambda:not w.refreshing)
        for mode in ('off','internet','local'):
            t.mode=mode;w.render(t.status())
            checks[mode+'_enabled']=w.actions['reveal-password'].get_enabled()
            w.actions['reveal-password'].activate(None)
            assert pump(lambda:w.secret_view is not None and not w.reveal_pending)
            d=w.secret_view
            checks[mode+'_masked']=not d.field.get_visibility() and d.buffer.get_text()==SECRET
            checks[mode+'_transport_wiped']=not any(t.last)
            d.show.emit('clicked');checks[mode+'_show']=d.field.get_visibility()
            d.show.emit('clicked');checks[mode+'_hide']=not d.field.get_visibility()
            d.copy.emit('clicked')
            copied=[]
            def read_done(clipboard,result):copied.append(clipboard.read_text_finish(result))
            w.get_clipboard().read_text_async(None,read_done)
            assert pump(lambda:bool(copied))
            checks[mode+'_copy']=copied.pop()==SECRET
            d.close();assert pump(lambda:d.cleared)
            checks[mode+'_cleared']=d.buffer.get_text()=='' and d.clipboard.get_content() is None
            w.secret_view=None
        for error in ('AUTHENTICATION_CANCELLED_OR_DENIED','SECRET_UNAVAILABLE','HELPER_FAILED'):
            t.fail=error;w.reveal_password();assert pump(lambda:not w.reveal_pending)
            checks[error]=w.secret_view is None and 'מצב הרשת לא השתנה' in w.notice.get_label()
        t.fail=None
        with patch.object(secret_dialog,'HIDE_SECONDS',1),patch.object(secret_dialog,'EXPIRE_SECONDS',3):
            w.reveal_password();assert pump(lambda:w.secret_view is not None)
            d=w.secret_view;d.toggle();d.copy_password()
            checks['automatic_hide']=pump(lambda:not d.field.get_visibility(),3)
            checks['clipboard_expires']=d.clipboard.get_content() is None
            checks['dialog_expires']=pump(lambda:d.cleared,4) and not d.buffer.get_text()
        w.secret_view=None;w.reveal_password();assert pump(lambda:w.secret_view is not None)
        d=w.secret_view;d.copy_password()
        d.clipboard.set('unrelated clipboard fixture')
        d.clear()
        copied=[];d.clipboard.read_text_async(None,lambda c,r:copied.append(c.read_text_finish(r)))
        assert pump(lambda:bool(copied));checks['unrelated_clipboard_preserved']=copied.pop()=='unrelated clipboard fixture'
        d.clipboard.set_content(None);d.close();w.secret_view=None
        for _ in range(3):
            w.reveal_password();assert pump(lambda:w.secret_view is not None)
            w.clear_secret();pump(seconds=.1)
        checks['repeated_reveal']=w.secret_view is None
        # Window hidden while auth pending: late delivery must wipe, not display.
        future=Future()
        with patch.object(w.pool,'submit',return_value=future):w.reveal_password()
        w.clear_secret();value=bytearray(SECRET.encode());future.set_result(dict(ok=True,secret=value))
        assert pump(lambda:not w.reveal_pending)
        checks['late_reply_wiped']=not any(value) and w.secret_view is None
        checks['no_network_actions']=set(t.calls)=={'reveal'}
        checks['unprivileged']=os.geteuid()!=0
        checks['rtl']=w.get_direction()==Gtk.TextDirection.RTL
    finally:
        w.dispose_view();w.close();pump(seconds=.3)
    print(json.dumps(dict(passed=all(checks.values()),checks=checks)))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
