import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('aag_package', ROOT / 'scripts/package.py')
pkg = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(pkg)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='aag-install-test-')
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_install_upgrade_uninstall_repeat_preserves_unrelated(self):
        keep = self.root / 'usr/share/applications/unrelated.desktop'
        keep.parent.mkdir(parents=True);keep.write_text('keep')
        result = pkg.install(self.root, False)
        self.assertFalse(result['activation']);self.assertFalse(result['autostart'])
        self.assertEqual(pkg.install(self.root, False)['changed_files'], 0)
        pkg.uninstall(self.root, False)
        self.assertEqual(pkg.uninstall(self.root, False)['removed_files'], 0)
        self.assertEqual(keep.read_text(), 'keep')

    def test_system_inspection_and_refresh_have_bounded_sanitized_commands(self):
        import subprocess
        with patch.object(pkg.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3, 'inactive\n', '')) as run:
            pkg.inactive(self.root, True)
            pkg.refresh(True)
        self.assertGreaterEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertGreater(call.kwargs.get('timeout', 0), 0)
            self.assertLessEqual(call.kwargs['timeout'], 30)
            self.assertEqual(call.kwargs.get('env', {}).get('PATH'), '/usr/sbin:/usr/bin:/sbin:/bin')
            self.assertTrue(call.args[0][0].startswith('/'))

    def test_uninstall_dry_run_validates_without_writes(self):
        pkg.install(self.root, False)
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        result = pkg.uninstall(self.root, False, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['validated_files'], len(pkg.source_map()))
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        (self.root / 'usr/bin/aag-hotspot').write_text('modified')
        with self.assertRaises(RuntimeError): pkg.uninstall(self.root, False, dry_run=True)

    def test_copy_failure_removes_only_files_written_by_this_attempt(self):
        original = pkg.atomic_file
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('fixture write failure')
            return original(*args)
        with patch.object(pkg, 'atomic_file', side_effect=fail_second):
            with self.assertRaises(OSError): pkg.install(self.root, False)
        self.assertEqual([p for p in self.root.rglob('*') if p.is_file()], [])

    def test_refresh_failure_restores_previous_receipt_and_payload(self):
        pkg.install(self.root, False)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        replacement = self.root / 'replacement-source';replacement.write_text('fixture upgrade')
        mapping = pkg.source_map();mapping[Path('usr/bin/aag-hotspot')] = replacement
        with patch.object(pkg, 'source_map', return_value=mapping), patch.object(pkg, 'refresh', side_effect=OSError('fixture refresh failure')):
            with self.assertRaises(OSError): pkg.install(self.root, False)
        replacement.unlink()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_preexisting_unowned_file_is_not_overwritten(self):
        file = self.root / 'usr/bin/aag-hotspot';file.parent.mkdir(parents=True);file.write_text('existing')
        with self.assertRaises(RuntimeError): pkg.install(self.root, False)
        self.assertEqual(file.read_text(), 'existing')

    def test_modified_installed_file_prevents_deletion_and_upgrade(self):
        pkg.install(self.root, False)
        file = self.root / 'usr/bin/aag-hotspot';file.write_text('modified')
        with self.assertRaises(RuntimeError): pkg.install(self.root, False)
        with self.assertRaises(RuntimeError): pkg.uninstall(self.root, False)
        self.assertEqual(file.read_text(), 'modified')

    def test_symlink_parent_is_not_followed(self):
        target = self.root / 'unrelated';target.mkdir()
        (self.root / 'usr').symlink_to(target, target_is_directory=True)
        with self.assertRaises(RuntimeError): pkg.install(self.root, False)
        self.assertEqual(list(target.iterdir()), [])

    def test_active_session_refuses_before_removing_files(self):
        pkg.install(self.root, False)
        session = self.root / 'run/aag-hotspot/private/session.json'
        session.parent.mkdir(parents=True);session.write_text('{}')
        with self.assertRaises(RuntimeError): pkg.uninstall(self.root, False)
        self.assertTrue((self.root / 'usr/bin/aag-hotspot').exists())

    def test_credentials_are_preserved_unless_purge_is_explicit(self):
        pkg.install(self.root, False)
        secret = self.root / 'var/lib/aag-hotspot/credentials.json'
        secret.parent.mkdir(parents=True);secret.write_text('fixture')
        pkg.uninstall(self.root, False)
        self.assertEqual(secret.read_text(), 'fixture')
        pkg.install(self.root, False)
        pkg.uninstall(self.root, False, purge=True)
        self.assertFalse(secret.exists())

    def test_uninstall_retires_only_off_runtime_and_refuses_unknown_files(self):
        import json
        pkg.install(self.root, False)
        runtime = self.root / 'run/aag-hotspot'
        (runtime / 'private').mkdir(parents=True)
        (runtime / 'status.json').write_text(json.dumps({'schema': 1, 'mode': 'off', 'phase': 'off'}))
        (runtime / 'unrelated').write_text('preserve')
        with self.assertRaises(RuntimeError): pkg.uninstall(self.root, False)
        self.assertTrue((runtime / 'unrelated').exists())
        (runtime / 'unrelated').unlink()
        pkg.uninstall(self.root, False)
        self.assertFalse(runtime.exists())


if __name__ == '__main__': unittest.main()
