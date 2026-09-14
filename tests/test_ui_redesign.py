"""Presentation/geometry checks only; backend semantics are tested unchanged."""
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from aag_hotspot.ui_support import Geometry,duration_label,icon_name,DEFAULT_SIZE
from aag_hotspot import tray
from gi.repository import GLib


class UIModelTests(unittest.TestCase):
    def test_human_connected_duration(self):
        self.assertEqual(duration_label(256),'4 דקות')
        self.assertEqual(duration_label(60),'דקה אחת')
        self.assertEqual(duration_label(30),'30 שניות')
        self.assertEqual(duration_label(3600),'שעה אחת')
        self.assertEqual(duration_label(7260),'2 שעות, דקה אחת')
        for invalid in (None,True,-1,'256'):self.assertEqual(duration_label(invalid),'לא ידוע')

    def test_geometry_roundtrip_is_private_and_contains_only_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'config/window.json';g=Geometry(p)
            self.assertEqual((g.load()['width'],g.load()['height']),DEFAULT_SIZE)
            self.assertTrue(g.save(540,660,True))
            self.assertEqual(g.load(),{'width':540,'height':660,'maximized':True})
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
            self.assertEqual(set(json.loads(p.read_text())),{'width','height','maximized'})

    def test_invalid_geometry_and_symlink_read_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'window.json';g=Geometry(p)
            for value in ({'width':True,'height':560,'maximized':False},{'width':200,'height':560,'maximized':False},
                          {'width':440,'height':10000,'maximized':False},{'width':440,'height':560,'maximized':False,'extra':'refused'}):
                p.write_text(json.dumps(value));self.assertEqual(g.load()['width'],440)
            target=Path(directory)/'target';target.write_text('{"width":600,"height":700,"maximized":false}')
            p.unlink();p.symlink_to(target);self.assertEqual(g.load()['width'],440)

    def test_untrusted_geometry_parent_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'config';p.mkdir();p.chmod(0o777)
            self.assertFalse(Geometry(p/'window.json').save(440,560,False))

    def test_tray_off_no_destructive_action_and_no_top_bar_text(self):
        indicator=tray.Indicator.__new__(tray.Indicator);indicator.value=tray.model({'mode':'off','clients':0})
        self.assertEqual([r[2] for r in indicator.value['rows'] if r[2]],['open'])
        self.assertEqual(indicator.property(None,None,None,tray.ITEM,'XAyatanaLabel').unpack(),'')
        self.assertFalse(indicator.property(None,None,None,tray.ITEM,'ItemIsMenu').unpack())

    def test_tray_active_only_open_and_off(self):
        for mode in ('internet','local'):
            model=tray.model({'mode':mode,'clients':2})
            self.assertEqual([r[2] for r in model['rows'] if r[2]],['open','off'])
            self.assertIn('2 מכשירים מחוברים',model['title'])
            self.assertEqual(model['icon'],icon_name(mode))

    def test_tray_activation_dispatch_opens_window(self):
        indicator=tray.Indicator.__new__(tray.Indicator);indicator.action=Mock();invocation=Mock()
        indicator.method(None,None,tray.PATH,tray.ITEM,'Activate',GLib.Variant('(ii)',(0,0)),invocation)
        indicator.action.assert_called_once_with('open');invocation.return_value.assert_called_once_with(None)

    def test_symbolic_assets_have_no_text_or_dots(self):
        import xml.etree.ElementTree as ET
        directory=Path(__file__).resolve().parents[1]/'desktop/icons/hicolor/scalable/status'
        for mode in ('off','local','internet'):
            root=ET.parse(directory/(icon_name(mode)+'.svg')).getroot()
            self.assertEqual(root.attrib['viewBox'],'0 0 16 16')
            self.assertEqual([x.tag.split('}')[-1] for x in root],['path'])


if __name__=='__main__':unittest.main()
