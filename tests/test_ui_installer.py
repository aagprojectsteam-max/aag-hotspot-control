"""UI-only file transaction tests in disposable staging directories."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ui_installer_test',ROOT/'scripts/install-ui.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)


class UIInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.receipt={'schema':1,'version':'0.2.0','files':{}}
        for rel in ('usr/lib/aag-hotspot/aag_hotspot/backend.py','usr/lib/aag-hotspot/aag_hotspot/gui.py','usr/lib/aag-hotspot/aag_hotspot/tray.py'):
            path=self.root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('previous '+rel);path.chmod(0o644)
            self.receipt['files'][rel]={'sha256':u.pkg.digest(path),'mode':0o644}
        self.manifest=self.root/u.pkg.MANIFEST;self.manifest.write_text(json.dumps(self.receipt));self.manifest.chmod(0o644)

    def test_ui_only_update_and_idempotency(self):
        before=u.inventory(self.root,self.receipt,{Path('usr/lib/aag-hotspot/aag_hotspot/gui.py'),Path('usr/lib/aag-hotspot/aag_hotspot/tray.py')})
        result=u.install(self.root);self.assertTrue(result['installed_source_match']);self.assertFalse(result['backend_installed'])
        after=u.inventory(self.root,json.loads(self.manifest.read_text()),set(u.payloads()))
        self.assertEqual(before,after);self.assertEqual(u.install(self.root)['changed_files'],0)

    def test_scope_cannot_expand_to_backend(self):
        with patch.object(u,'payloads',return_value={Path('usr/lib/aag-hotspot/aag_hotspot/backend.py'):ROOT/'lib/aag_hotspot/backend.py'}):
            with self.assertRaisesRegex(RuntimeError,'scope'):u.install(self.root)

    def test_modified_installed_backend_refuses_before_writing(self):
        (self.root/'usr/lib/aag-hotspot/aag_hotspot/backend.py').write_text('user changed')
        with patch.object(u.pkg,'atomic_file') as write:
            with self.assertRaises(RuntimeError):u.install(self.root)
            write.assert_not_called()

    def test_partial_ui_write_failure_restores_old_receipt_and_ui(self):
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original=u.pkg.atomic_file;count=0
        def fail(path,data,mode):
            nonlocal count
            count+=1
            if count==3:raise OSError('fixture')
            return original(path,data,mode)
        with patch.object(u.pkg,'atomic_file',side_effect=fail):
            with self.assertRaises(OSError):u.install(self.root)
        after={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
