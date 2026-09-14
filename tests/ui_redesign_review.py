#!/usr/bin/python3
"""Real GTK views and session SNI; fixture states only, never networking actions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch
sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, '/usr/lib/aag-hotspot' if '--installed' in sys.argv else str(ROOT/'lib'))
from aag_hotspot import gui, tray
from aag_hotspot.ui_support import Geometry, icon_directory
from gi.repository import Adw, Gio, GLib, Gtk
OUT=ROOT/'build/gui-review'


def state(mode='off', count=0):
    rows=[{'mac':f'02:00:00:00:00:{i+1:02x}','ipv4':f'10.77.0.{21+i}',
           'hostname':'ubuntu-tablet' if i==0 else ('workspace-'+str(i)),
           'signal_dbm':-29-i*6,'connected_seconds':256+i*70} for i in range(count)]
    return {'mode':mode,'phase':'off' if mode=='off' else 'active','health':'OK','installed':True,'configured':True,
            'ssid':'AAG-Hotspot','uplink':'wwan0','clients':count,'client_count':count,'client_details':rows,
            'client_data_status':'OFF' if mode=='off' else 'OK','clients_updated_monotonic':time.monotonic()}


class Transport:
    def __init__(self): self.value=state();self.calls=[];self.reads=0
    def status(self):
        self.reads+=1;self.value['clients_updated_monotonic']=time.monotonic();return dict(self.value)
    def request(self, action, password=None):
        self.calls.append(action)
        if action in ('internet','local','off'): self.value=state(action,0)
        return {'ok':True,'status':self.status()}
    def doctor(self):return {'checks':{'helper_installed':True,'password_configured':True,'cellular_public_route':True}}


def pump(check=lambda:False, seconds=.16, required=False):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        if check():return
        time.sleep(.01)
    if required:raise RuntimeError('UI_REVIEW_TIMEOUT')


def shot(widget,name):
    pump()
    paintable=Gtk.WidgetPaintable.new(widget);snapshot=Gtk.Snapshot.new()
    paintable.snapshot(snapshot,float(widget.get_width()),float(widget.get_height()))
    node=snapshot.to_node()
    if node is None:raise RuntimeError('NO_RENDERED_WIDGET')
    texture=widget.get_native().get_renderer().render_texture(node,None)
    if not texture.save_to_png(str(OUT/name)):raise RuntimeError('SCREENSHOT_SAVE_FAILED')


def main():
    if os.geteuid()==0:return 2
    OUT.mkdir(parents=True,exist_ok=True)
    Gtk.Settings.get_default().set_property('gtk-enable-animations',False)
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    t=Transport();app=gui.Application(t);app.set_application_id('org.aag.Hotspot.UIReview');app.register(None)
    if app.get_is_remote():raise RuntimeError('Review app already running')
    checks={};sizes=[]
    with tempfile.TemporaryDirectory(prefix='aag-ui-geometry-') as directory:
        geometry=Geometry(Path(directory)/'window.json')
        w=gui.Window(app,t,geometry);w.present()
        app.tray=tray.Indicator(app.tray_action)
        def settled():pump(lambda:not w.refreshing and not w.busy and w.get_mapped(),5,True);pump()
        def render(mode,count):t.value=state(mode,count);w.refresh();settled();sizes.append([w.get_width(),w.get_height()])
        try:
            with patch('subprocess.run',side_effect=AssertionError('No network/process actions permitted')):
                settled();pump(lambda:app.tray.registered,6,True)
                checks['native_tray_registered']=app.tray.registered
                baseline=(w.get_width(),w.get_height())
                checks['default_geometry']=baseline==(440,560)
                checks['off_primary_actions']={k for k,b in w.buttons.items() if b.get_visible()}=={'internet','local'}
                checks['off_no_off_button']=not w.buttons['off'].get_visible()
                checks['off_no_uplink_row']=not w.info_rows['source'].get_visible()
                checks['secondary_header_menu']=w.header_menu.get_menu_model() is w.menu_model
                shot(w,'off.png')
                for mode in ('internet','local'):
                    for count in (0,1,3):
                        render(mode,count)
                        checks[f'{mode}_{count}_primary_actions']={k for k,b in w.buttons.items() if b.get_visible()}=={'off'}
                        checks[f'{mode}_{count}_count']=w.values['clients'].get_label()==str(count)
                        checks[f'{mode}_{count}_secondary_switch']=w.switch_mode.get_visible()
                        checks[f'{mode}_{count}_geometry']=(w.get_width(),w.get_height())==baseline
                        if count==1:shot(w,mode+'.png')
                checks['local_no_internet_label']=w.info_rows['source'].get_title()=='אינטרנט משותף' and w.values['source'].get_label()=='לא'
                w.actions['mode-internet'].activate(None);settled()
                checks['secondary_switch_dispatch']=t.calls[-1]=='internet'
                render('internet',1);w.info_rows['clients'].emit('activated');settled()
                checks['separate_client_page']=w.navigation.get_visible_page() is w.devices_page
                checks['devices_page_geometry']=(w.get_width(),w.get_height())==baseline
                mac=t.value['client_details'][0]['mac'];row=w.client_rows[mac]
                checks['human_duration']=row['values']['time'].get_label()=='4 דקות'
                checks['bidi']={row['values'][k].get_direction() for k in ('ipv4','mac','signal')}=={Gtk.TextDirection.LTR}
                shot(w,'connected-devices.png')
                t.value['client_details'][0]['ipv4']='10.77.0.28';w.refresh();settled()
                checks['new_ip_replaces_old']=row['values']['ipv4'].get_label()=='10.77.0.28' and w.client_rows[mac] is row
                clipboard=Mock()
                with patch.object(w,'get_clipboard',return_value=clipboard):
                    row['copy'].emit('clicked');checks['copy_current_ip']=clipboard.set.call_args.args==('10.77.0.28',)
                    w.current['clients_updated_monotonic']=0;clipboard.reset_mock();w.copy_ip(mac)
                    checks['stale_copy_refused']=not clipboard.set.called
                t.value['client_details'][0]['hostname']=None;w.refresh();settled()
                checks['unknown_hostname']=row['row'].get_title()=='לא ידוע'
                t.value['client_details'][0]['hostname']='very-long-hostname-'*12;w.refresh();settled()
                checks['long_hostname_stable']=(w.get_width(),w.get_height())==baseline
                shot(w,'long-hostname.png')
                w.set_default_size(360,480);pump(seconds=.4)
                checks['narrow_geometry']=(w.get_width(),w.get_height())==(360,480)
                shot(w,'narrow.png')
                render('local',8);checks['many_clients_scroll']=w.devices_scroll.get_vadjustment().get_upper()>w.devices_scroll.get_vadjustment().get_page_size()
                checks['many_clients_no_growth']=(w.get_width(),w.get_height())==(360,480)
                w.navigation.pop();pump();checks['back_navigation']=w.navigation.get_visible_page() is w.main_page
                w.set_default_size(540,660);pump(seconds=.4);render('local',1)
                checks['resized_geometry']=(w.get_width(),w.get_height())==(540,660)
                shot(w,'user-resized.png')
                w.save_geometry();checks['geometry_persisted']=geometry.load()=={'width':540,'height':660,'maximized':False}
                reopened=gui.Window(app,t,geometry);reopened.present()
                pump(lambda:reopened.get_mapped() and not reopened.refreshing,3,True)
                checks['geometry_restored_on_new_window']=(reopened.get_width(),reopened.get_height())==(540,660)
                reopened.dispose_view();reopened.destroy();w.present()
                w.set_default_size(440,560);pump(seconds=.3)
                render('off',0);w.show_clients();pump()
                checks['empty_state']=w.client_stack.get_visible_child_name()=='empty' and w.empty_clients.get_title()=='אין מכשירים מחוברים כרגע'
                shot(w,'devices-empty.png');w.navigation.pop();pump()
                w.actions['password'].activate(None);pump(lambda:w.get_visible_dialog() is not None,3,True)
                checks['password_menu_opens_masked_dialog']=w.get_visible_dialog().get_title()=='סיסמת הרשת' and 'configure' not in t.calls
                w.get_visible_dialog().close();pump()
                w.actions['diagnose'].activate(None);pump(lambda:w.get_visible_dialog() is not None,3,True)
                checks['diagnostics_menu']=w.get_visible_dialog().get_heading()=='אבחון'
                w.get_visible_dialog().close();pump()
                checks['rtl']=w.get_direction()==Gtk.TextDirection.RTL and all(b.get_direction()==Gtk.TextDirection.RTL for b in w.buttons.values())
                for mode,count in (('off',0),('internet',1),('local',3)):
                    render(mode,count);m=app.tray.value
                    checks['tray_'+mode+'_no_label']=app.tray.property(None,None,None,tray.ITEM,'XAyatanaLabel').unpack()==''
                    checks['tray_'+mode+'_symbolic']=m['icon'].endswith('-symbolic')
                    checks['tray_'+mode+'_minimal']=set(r[2] for r in m['rows'] if r[2])<= {'open','off'}
                    checks['tray_'+mode+'_tooltip']='AAG Hotspot' in m['title']
                w.close();checks['close_to_tray']=not w.get_visible() and not w.closed
                invocation=Mock();app.tray.method(None,None,tray.PATH,tray.ITEM,'Activate',GLib.Variant('(ii)',(0,0)),invocation)
                settled();checks['tray_activate_opens_app']=w.get_visible()
                Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
                render('internet',1);shot(w,'dark-internet.png');w.show_clients();pump();shot(w,'dark-devices.png')
                checks['dark_theme']=Adw.StyleManager.get_default().get_dark()
                # A native GTK preview uses the actual exported icon/tooltip/menu
                # model. These are labelled previews, not GNOME panel captures.
                preview=Gtk.Window(title='Tray preview',default_width=280,default_height=100)
                box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
                for edge in ('top','bottom','start','end'):getattr(box,'set_margin_'+edge)(16)
                strip=Gtk.Box(spacing=20,halign=Gtk.Align.CENTER)
                image=Gtk.Image(pixel_size=20);strip.append(image);box.append(strip)
                caption=Gtk.Label(wrap=True);box.append(caption);preview.set_child(box);preview.present();pump()
                for mode,name in [('off','tray-off.png'),('internet','tray-active.png')]:
                    model=tray.model(state(mode,0 if mode=='off' else 1));image.set_from_icon_name(model['icon']);caption.set_label(model['title']);shot(preview,name)
                preview.close();checks['light_theme']=True
                matrix=Gtk.Window(title='Symbolic icon size review')
                grid=Gtk.Grid(column_spacing=20,row_spacing=16)
                for edge in ('top','bottom','start','end'):getattr(grid,'set_margin_'+edge)(20)
                for column,size in enumerate((16,20,24)):
                    grid.attach(Gtk.Label(label=str(size)+' px'),column+1,0,1,1)
                for row,mode in enumerate(('off','local','internet'),1):
                    grid.attach(Gtk.Label(label=mode),0,row,1,1)
                    for column,size in enumerate((16,20,24)):
                        glyph=Gtk.Image(icon_name=tray.model(state(mode))['icon'],pixel_size=size)
                        grid.attach(glyph,column+1,row,1,1)
                matrix.set_child(grid);matrix.present();pump()
                shot(matrix,'symbolic-icons-dark.png')
                Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
                shot(matrix,'symbolic-icons-light.png');matrix.close()
                checks['network_actions_mocked']=True
        finally:
            app.exiting=True;app.tray.close();w.close();Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
    result={'passed':all(checks.values()),'checks':checks,'state_geometry':sizes,'uid':os.geteuid(),
            'network_actions':False,'client_data':'FIXTURES_ONLY','installed':'--installed' in sys.argv,
            'tray_screenshots':'NATIVE_GTK_PREVIEWS_OF_EXPORTED_MODEL'}
    (OUT/('installed-gui-tests.json' if '--installed' in sys.argv else 'gui-tests.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
