#!/usr/bin/python3
"""Installed GUI observer: reveal/copy only; never starts or stops networking.

Outputs booleans only. Real credential stays in the GTK secure buffer/clipboard;
no screenshot, text assertion, exception body, or subprocess response is emitted.
"""
import json
import os
import resource
import sys
import time
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
sys.path.insert(0,'/usr/lib/aag-hotspot')
from aag_hotspot.gui import Application, Window, GLib
from aag_hotspot import client


def pump(until, seconds=125):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        if until():return True
        time.sleep(.02)
    return False


def main():
    checks={};w=None
    try:
        assert os.geteuid()!=0 and len(sys.argv)==2 and sys.argv[1] in ('off','internet','local')
        mode=sys.argv[1];before=client.status();assert before['mode']==mode
        app=Application();app.set_application_id('org.aag.Hotspot.LivePasswordCheck');app.register(None)
        w=Window(app);w.present();assert pump(lambda:not w.refreshing,10)
        w.actions['reveal-password'].activate(None)
        assert pump(lambda:not w.reveal_pending)
        d=w.secret_view;assert d is not None
        checks['masked']=not d.field.get_visibility() and d.buffer.get_length()>=12
        d.show.emit('clicked');checks['revealed']=d.field.get_visibility()
        d.copy.emit('clicked');copied=[]
        def copied_done(clipboard,result):
            try:copied.append(clipboard.read_text_finish(result)==d.buffer.get_text())
            except Exception:copied.append(False)
        d.clipboard.read_text_async(None,copied_done)
        assert pump(lambda:bool(copied),5)
        checks['copied']=copied.pop()
        d.hide_password();checks['hidden']=not d.field.get_visibility()
        d.close();assert pump(lambda:d.cleared,5)
        checks['cleared']=d.buffer.get_length()==0 and d.clipboard.get_content() is None
        after=client.status()
        checks['same_mode_and_interface']=all(before.get(k)==after.get(k) for k in ('mode','phase','interface'))
        checks['gui_unprivileged']=os.geteuid()!=0
    except Exception:
        checks['secret_safe_failure']=False
    finally:
        if w is not None:w.dispose_view();w.close()
    print(json.dumps({'passed':bool(checks) and all(checks.values()),'checks':checks}))
    return 0 if checks and all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
