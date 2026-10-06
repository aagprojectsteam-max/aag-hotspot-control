"""Language settings and translation contracts; never touch real preferences."""
import contextlib
import gettext
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from aag_hotspot import i18n,cli,tray
from aag_hotspot.gui import presentation,error_message
from aag_hotspot.ui_support import Geometry,duration_label


class LanguageTests(unittest.TestCase):
    def setUp(self):
        previous=i18n.language();self.addCleanup(i18n.set_language,previous)
        i18n.set_language('en')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'settings'

    def test_fresh_profile_is_english_even_on_hebrew_desktop(self):
        with patch.dict(os.environ,{'LANG':'he_IL.UTF-8','LANGUAGE':'he'}):
            settings=i18n.LanguageSettings(self.directory)
        self.assertEqual(settings.language,'en');self.assertFalse(settings.migrated)
        value=json.loads((self.directory/'preferences.json').read_text())
        self.assertEqual(value,{'schema':1,'language':'en'})
        self.assertEqual(stat.S_IMODE((self.directory/'preferences.json').stat().st_mode),0o600)

    def test_trusted_legacy_geometry_migrates_once_and_explicit_selection_wins(self):
        Geometry(self.directory/'window.json').save(440,560,False)
        first=i18n.LanguageSettings(self.directory)
        self.assertEqual(first.language,'he');self.assertTrue(first.migrated)
        self.assertTrue(first.save('en'))
        restarted=i18n.LanguageSettings(self.directory)
        self.assertEqual(restarted.language,'en');self.assertFalse(restarted.migrated)

    def test_preferences_persist_both_directions(self):
        for code in ('he','en','he'):
            settings=i18n.LanguageSettings(self.directory);self.assertTrue(settings.save(code))
            self.assertEqual(i18n.LanguageSettings(self.directory).language,code)

    def test_untrusted_or_invalid_legacy_file_is_not_migration_evidence(self):
        self.directory.mkdir(mode=0o700)
        p=self.directory/'window.json';p.write_text('{}');p.chmod(0o600)
        self.assertEqual(i18n.LanguageSettings(self.directory).language,'en')
        (self.directory/'preferences.json').unlink()
        p.unlink();p.symlink_to('/dev/null')
        self.assertEqual(i18n.LanguageSettings(self.directory).language,'en')

    def test_settings_symlink_and_untrusted_parent_are_not_written(self):
        self.directory.mkdir(mode=0o700);target=Path(self.tmp.name)/'target';target.write_text('keep')
        (self.directory/'preferences.json').symlink_to(target)
        settings=i18n.LanguageSettings(self.directory)
        self.assertTrue(settings.error);self.assertFalse(settings.save('he'))
        self.assertEqual(target.read_text(),'keep')
        (self.directory/'preferences.json').unlink();self.directory.chmod(0o777)
        self.assertFalse(settings.save('en'))

    def test_invalid_preference_falls_back_without_overwriting(self):
        self.directory.mkdir(mode=0o700)
        p=self.directory/'preferences.json'
        for value in ({'schema':1,'language':'bad'},{'schema':True,'language':'he'},[],{'schema':1,'language':['he']}):
            p.write_text(json.dumps(value));p.chmod(0o600)
            settings=i18n.LanguageSettings(self.directory)
            self.assertEqual(settings.language,'en');self.assertTrue(settings.error)
            self.assertEqual(json.loads(p.read_text()),value)

    def test_english_model_modes_counts_and_errors(self):
        self.assertEqual(presentation({'mode':'off'})['mode'],'Hotspot is off')
        self.assertEqual(presentation({'mode':'internet'})['mode'],'Internet hotspot')
        self.assertEqual(presentation({'mode':'local'})['mode'],'Local only')
        self.assertEqual(tray.count_label(1),'1 device connected')
        self.assertEqual(tray.count_label(2),'2 devices connected')
        self.assertEqual(duration_label(7260),'2 hours, 1 minute')
        self.assertIn('cancelled or denied',error_message('AUTHENTICATION_CANCELLED_OR_DENIED'))
        self.assertIn('cannot be shared safely',error_message('UNSUPPORTED_UPLINK'))

    def test_hebrew_catalog_modes_errors_plurals_and_back_to_english(self):
        i18n.set_language('he');self.assertEqual(i18n.direction(),'rtl')
        for value in ('off','internet','local'):
            self.assertRegex(presentation({'mode':value})['mode'],'[\u0590-\u05ff]')
        for code in ('AUTHENTICATION_CANCELLED_OR_DENIED','SECRET_UNAVAILABLE','WIFI_STA_UNVALIDATED','UNSUPPORTED_UPLINK'):
            self.assertRegex(error_message(code),'[\u0590-\u05ff]')
        for count in (0,1,2,10):self.assertRegex(tray.count_label(count),'[\u0590-\u05ff]')
        i18n.set_language('en');self.assertEqual(i18n.direction(),'ltr')
        self.assertEqual(tray.model({'mode':'off'})['title'],'AAG Hotspot — Off')

    def test_cli_machine_output_does_not_depend_on_gui_language(self):
        outputs=[];status={'mode':'local','uplink':'wwan0','clients':0,'health':'OK','client_details':[]}
        for language in ('en','he'):
            i18n.set_language(language);out=io.StringIO()
            with contextlib.redirect_stdout(out),patch.object(cli.client,'status',return_value=status):
                self.assertEqual(cli.main(['status']),0)
            outputs.append(out.getvalue())
        self.assertEqual(*outputs);self.assertIn('MODE=local',outputs[0]);self.assertIn('UPLINK=wwan0',outputs[0])

    def test_translation_resources_are_complete_and_match_runtime(self):
        path=Path(__file__).resolve().parents[1]/'scripts/check-i18n.py'
        spec=importlib.util.spec_from_file_location('catalog_check',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertTrue(module.check()['passed'])


if __name__=='__main__':unittest.main()
