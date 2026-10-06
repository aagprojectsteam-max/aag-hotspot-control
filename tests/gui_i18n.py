#!/usr/bin/python3
"""Real GTK bilingual matrix; fixture transport only, no networking actions."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/usr/lib/aag-hotspot' if '--installed' in sys.argv else str(ROOT/'lib'))
from aag_hotspot import gui,i18n,tray
from aag_hotspot.ui_support import Geometry
from gi.repository import Adw,Gio,GLib,Gtk
OUT=ROOT/'build/i18n-review'


def pump(until=lambda:False, seconds=.15, required=False):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        if until():return True
        time.sleep(.01)
    if required:raise AssertionError('UI test deadline exceeded')
    return bool(until())


def shot(window,name):
    pump();paintable=Gtk.WidgetPaintable.new(window);snapshot=Gtk.Snapshot.new()
    paintable.snapshot(snapshot,float(window.get_width()),float(window.get_height()))
    texture=window.get_renderer().render_texture(snapshot.to_node(),None)
    assert texture.save_to_png(str(OUT/name))


class Transport:
    def __init__(self):self.calls=[];self.value=self.state('off')
    @staticmethod
    def state(mode):
        rows=[] if mode=='off' else [dict(mac='02:00:00:00:00:01',hostname='example-tablet',ipv4='10.77.0.15',signal_dbm=-29,connected_seconds=7260)]
        return dict(mode=mode,phase='off' if mode=='off' else 'active',health='OK',configured=True,installed=True,
                    ssid='AAG-Hotspot',uplink='cell42',uplink_type='NONE_REQUIRED' if mode=='local' else 'CELLULAR',uplink_connection='Mobile data',interface=None if mode=='off' else 'aaghp12345678',
                    client_count=len(rows),clients=len(rows),client_details=rows,client_data_status='OFF' if mode=='off' else 'OK',clients_updated_monotonic=time.monotonic())
    def status(self):return copy.deepcopy(self.value)
    def request(self,*args):self.calls.append(args);raise AssertionError('Network action forbidden')
    def reveal_password(self):return dict(ok=True,secret=bytearray(b'synthetic-test-password'))
    def doctor(self):return dict(checks=dict(helper_installed=True,password_configured=True,uplink_supported=True,cellular_public_route=True))


def main():
    assert os.geteuid()!=0
    OUT.mkdir(parents=True,exist_ok=True)
    Gtk.Settings.get_default().set_property('gtk-enable-animations',False)
    checks={};t=Transport()
    with tempfile.TemporaryDirectory(prefix='aag-i18n-') as temp:
        directory=Path(temp);settings=i18n.LanguageSettings(directory)
        app=gui.Application(t,settings=settings);app.set_application_id('org.aag.Hotspot.I18nTest');app.register(None)
        window=gui.Window(app,t,Geometry(directory/'window.json'));window.present()
        pump(lambda:not window.refreshing,3,True)
        bus=Gio.DBusConnection.new_for_address_sync(os.environ['DBUS_SESSION_BUS_ADDRESS'],Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
        app.tray=tray.Indicator(app.tray_action,bus)
        checks['fresh_english']=i18n.language()=='en' and window.mode.get_label()=='Hotspot is off'
        try:
            for theme,scheme in [('light',Adw.ColorScheme.FORCE_LIGHT),('dark',Adw.ColorScheme.FORCE_DARK)]:
                Adw.StyleManager.get_default().set_color_scheme(scheme)
                for language in ('en','he','en'):
                    window.settings_dialog();pump()
                    row=window.settings_widgets[0]
                    before=copy.deepcopy(t.value);pid=os.getpid();calls=list(t.calls)
                    row.set_selected(['en','he'].index(language));pump()
                    checks[theme+'_'+language+'_selection']=i18n.language()==language
                    checks[theme+'_'+language+'_settings_direction']=window.settings_view.get_direction()==gui.text_direction()
                    checks[theme+'_'+language+'_saved']=i18n.LanguageSettings(directory).language==language
                    checks[theme+'_'+language+'_same_process']=os.getpid()==pid
                    checks[theme+'_'+language+'_no_network_command']=t.calls==calls and t.value==before
                    if theme=='light':shot(window,language+'-settings.png')
                    window.settings_view.close();pump()
                    for mode in ('off','internet','local'):
                        key=theme+'_'+language+'_'+mode
                        t.value=t.state(mode);window.render(t.status());pump()
                        expected={'off':'Hotspot is off','internet':'Internet hotspot','local':'Local only'}[mode]
                        checks[key+'_mode']=window.mode.get_label()==i18n._(expected)
                        checks[key+'_direction']=window.get_direction()==gui.text_direction()
                        checks[key+'_ssid_ltr']=window.values['ssid'].get_direction()==Gtk.TextDirection.LTR
                        checks[key+'_geometry']=window.get_width()==440 and window.get_height()==560
                        checks[key+'_tray']=app.tray.value==tray.model(window.current)
                        checks[key+'_tray_direction']=app.tray.property(None,None,None,tray.MENU,'TextDirection').unpack()==i18n.direction()
                        if theme=='light':shot(window,language+'-'+mode+'.png')
                        before=copy.deepcopy(t.value);window.change_language('he' if language=='en' else 'en');window.change_language(language)
                        checks[key+'_mode_survives_switch']=t.value==before and window.current['mode']==mode and window.current['interface']==before['interface'] and not t.calls
                        window.reveal_password();pump(lambda:window.secret_view is not None and not window.reveal_pending,3,True)
                        d=window.secret_view
                        checks[key+'_password']=d.get_title()==i18n._('Wi-Fi password') and d.copy.get_tooltip_text()==i18n._('Copy password')
                        checks[key+'_password_direction']=d.get_direction()==gui.text_direction() and d.field.get_direction()==Gtk.TextDirection.LTR
                        checks[key+'_password_masked']=not d.field.get_visibility()
                        if theme=='light' and mode=='off':shot(window,language+'-password.png')
                        window.change_language('he' if language=='en' else 'en')
                        checks[key+'_switch_clears_secret']=d.cleared and not d.buffer.get_length()
                        window.change_language(language);pump()
                        if mode!='off':
                            window.show_clients();pump(lambda:not window.refreshing,3,True)
                            card=window.client_rows['02:00:00:00:00:01']
                            checks[key+'_devices_title']=window.devices_page.get_title()==i18n._('Connected devices')
                            checks[key+'_copy_ip']=card['copy'].get_label()==i18n._('Copy IP address')
                            checks[key+'_bidi']=all(card['values'][k].get_direction()==Gtk.TextDirection.LTR for k in ('ipv4','mac','signal'))
                            checks[key+'_values']=card['values']['ipv4'].get_label()=='10.77.0.15' and card['values']['mac'].get_label()=='02:00:00:00:00:01'
                            if theme=='light':shot(window,language+'-devices.png')
                            window.navigation.pop();pump()
                    for code in ('AUTHENTICATION_CANCELLED_OR_DENIED','WIFI_STA_UNVALIDATED','UNSUPPORTED_UPLINK','HELPER_UNAVAILABLE','NM_DEVICE_READINESS_TIMEOUT'):
                        text=gui.error_message(code)
                        checks[theme+'_'+language+'_'+code]=bool(text) and (any('\u0590'<=c<='\u05ff' for c in text) if language=='he' else not any('\u0590'<=c<='\u05ff' for c in text))
                    window.diagnose();pump(lambda:window.get_visible_dialog() is not None,3,True)
                    checks[theme+'_'+language+'_diagnostics']=window.get_visible_dialog().get_heading()==i18n._('Diagnostics')
                    window.get_visible_dialog().close();pump()
                    # Stress strings at narrow window size, retaining technical LTR.
                    t.value=t.state('local');t.value['client_details'][0].update(hostname='long-device-name-'*12,connected_seconds=9999999)
                    window.render(t.status());window.set_default_size(360,520);window.show_clients();pump()
                    checks[theme+'_'+language+'_long_strings_fit']=window.get_width()==360 and window.get_height()==520
                    window.navigation.pop();window.set_default_size(440,560);pump()
            checks['no_control_calls']=not t.calls
            checks['settings_failure_preserves_language']=True
            window.settings_dialog();pump();previous=i18n.language()
            with patch.object(settings,'save',return_value=False):
                checks['settings_failure_preserves_language']=not window.change_language('he') and i18n.language()==previous and window.settings_notice.get_visible()
            window.settings_view.close();pump()
        finally:
            app.tray.close();app.tray=None;bus.close_sync(None)
            window.dispose_view();window.close();pump()
    result=dict(passed=all(checks.values()),checks=checks,check_count=len(checks),network_actions=False,active_modes='FIXTURE_ONLY',installed='--installed' in sys.argv)
    (OUT/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
