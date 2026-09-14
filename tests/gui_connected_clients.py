#!/usr/bin/python3
"""Real GTK + real session tray protocol, fixture clients, no network actions."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, '/usr/lib/aag-hotspot' if '--installed' in sys.argv else str(ROOT / 'lib'))
from aag_hotspot import gui, tray
from gi.repository import Gio, GLib

MAC = '02:00:00:00:00:01'


class Transport:
    def __init__(self):
        self.calls=[]; self.reads=0; self.delay=0
        self.value={'mode':'local','phase':'active','health':'OK','installed':True,'configured':True,
                    'ssid':'AAG-Hotspot','clients':1,'client_count':1,'client_data_status':'OK',
                    'client_details':[{'mac':MAC,'hostname':None,'ipv4':'10.77.0.15','signal_dbm':-29,'connected_seconds':256}],
                    'clients_updated_monotonic':time.monotonic()}
    def status(self):
        self.reads+=1
        time.sleep(self.delay)
        self.value['clients_updated_monotonic']=time.monotonic()
        return dict(self.value)
    def request(self, action, password=None):
        self.calls.append(action)
        self.value.update(mode=action,phase='off' if action=='off' else 'active')
        return {'ok':True,'status':self.status()}


def main():
    if os.geteuid()==0: return 2
    t=Transport(); app=gui.Application(t); app.set_application_id('org.aag.Hotspot.ClientViewTest')
    app.register(None)
    if app.get_is_remote(): raise RuntimeError('Test already running')
    window=gui.Window(app,t);window.set_title('AAG Hotspot — בדיקת תצוגה');window.present()
    bus=Gio.DBusConnection.new_for_address_sync(os.environ['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
    app.tray=tray.Indicator(app.tray_action,bus)
    reader=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    checks={}
    def wait(check, seconds=10):
        deadline=time.monotonic()+seconds
        while not check():
            if time.monotonic()>deadline: raise RuntimeError('GUI_TRAY_TEST_TIMEOUT')
            while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
            time.sleep(.01)
    def settled(): wait(lambda:not window.refreshing and not window.busy and window.get_mapped())
    def call(path, interface, method, args):
        result=[]
        def done(connection, response):
            try:result.append(connection.call_finish(response))
            except Exception:result.append(None)
        reader.call(bus.get_unique_name(),path,interface,method,args,None,Gio.DBusCallFlags.NONE,3000,None,done)
        wait(lambda:bool(result))
        if result[0] is None:raise RuntimeError('TRAY_PROTOCOL_FAILED')
        return result[0].unpack()
    try:
        with patch('subprocess.run',side_effect=AssertionError('Network/process action forbidden')):
            settled();wait(lambda:app.tray.registered)
            checks['tray_registered_with_real_gnome_host']=app.tray.registered
            checks['hebrew_rtl']=window.get_direction()==gui.Gtk.TextDirection.RTL
            row=window.client_rows[MAC]['row']
            checks['unknown_hostname']=row.get_title()=='לא ידוע'
            checks['all_fields']=all(x in ' '.join(v.get_label() for v in window.client_rows[MAC]['values'].values()) for x in ('10.77.0.15',MAC,'-29','4 דקות'))
            props=call(tray.PATH,'org.freedesktop.DBus.Properties','GetAll',GLib.Variant('(s)',(tray.ITEM,)))[0]
            checks['tray_current_count']=props['XAyatanaLabel']=='' and '1 מכשיר מחובר' in props['Title']
            layout=call(tray.MENU_PATH,tray.MENU,'GetLayout',GLib.Variant('(iias)',(0,-1,[])))
            checks['dbusmenu_layout']=len(layout[1][2])==6
            checks['rtl_dbusmenu']=call(tray.MENU_PATH,'org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',(tray.MENU,'TextDirection')))[0]=='rtl'
            t.value['client_details'][0].update(ipv4='10.77.0.40',hostname='fixture-tablet')
            previous=t.reads;window.refresh();settled()
            checks['manual_refresh_new_ip']=t.reads>previous and window.client_rows[MAC]['values']['ipv4'].get_label()=='10.77.0.40'
            checks['stable_mac_row']=window.client_rows[MAC]['row'] is row
            clipboard=Mock()
            with patch.object(window,'get_clipboard',return_value=clipboard):
                window.client_rows[MAC]['copy'].emit('clicked')
                checks['copy_current_ip']=clipboard.set.call_args.args==('10.77.0.40',)
                window.current['clients_updated_monotonic']=0
                clipboard.reset_mock();window.copy_ip(MAC)
                checks['copy_stale_ip_refused']=not clipboard.set.called
            window.refresh();settled()
            t.delay=.3;heartbeat=[];GLib.timeout_add(30,lambda:heartbeat.append(True) and False)
            window.refresh();settled();checks['nonblocking_refresh']=bool(heartbeat);t.delay=0
            previous=t.reads;wait(lambda:t.reads>previous,7);settled();checks['automatic_refresh']=True
            for mode in ('internet','local'):
                window.actions['mode-'+mode].activate(None)
                wait(lambda:t.calls and t.calls[-1]==mode);settled()
                checks['secondary_'+mode+'_fixture_dispatch']=window.current['mode']==mode
            t.value.update(clients=0,client_count=0,client_details=[]);window.refresh();settled()
            checks['disconnect_clears_list']=not window.client_rows
            checks['tray_count_update']='0 מכשירים מחוברים' in app.tray.value['title']
            window.close();checks['close_keeps_tray']=not window.get_visible() and not window.closed
            app.activate();settled();checks['launcher_reuses_hidden_window']=len(app.get_windows())==1
            app.tray_action('clients');settled();checks['tray_reopens_clients']=window.get_visible()
            checks['unprivileged']=os.geteuid()!=0
    finally:
        app.exiting=True;app.tray.close();window.close();bus.close_sync(None)
    print(json.dumps({'passed':all(checks.values()),'checks':checks,'data':'FIXTURE_ONLY',
                      'network_actions':False,'installed':'--installed' in sys.argv},ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
