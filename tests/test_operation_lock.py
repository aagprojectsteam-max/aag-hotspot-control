"""Real kernel flocks on temporary directories + memory-only network lifecycle."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_production import MemoryStore, MemoryBackend
from aag_hotspot import state, helper, ownership as rb, policy
from aag_hotspot.controller import Controller

ROOT = Path(__file__).resolve().parents[1]


class LockedMemoryStore(MemoryStore, state.Store):
    """Real Store.locked, in-memory journal/backend; never access host networking."""


class OperationLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aag-lock-test-')
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.private = self.runtime / 'private'; self.private.mkdir(mode=0o700)
        original_lstat = Path.lstat
        def parent_metadata(path):
            # Sandbox may map host UID 0 to nobody. Only fixed parent metadata
            # is mocked; all temporary inode opens/flocks stay real.
            if str(path) in ('/run', '/var', '/var/lib'):
                return SimpleNamespace(st_mode=0o40755, st_uid=0)
            return original_lstat(path)
        for item in (patch.object(state, 'RUNTIME', self.runtime),
                     patch.object(state, 'PRIVATE', self.private),
                     patch.object(state.os, 'geteuid', return_value=0),
                     patch.object(state, 'trusted_dir'),
                     patch.object(Path, 'lstat', parent_metadata),
                     patch('subprocess.run', side_effect=AssertionError('No live commands')),
                     patch('subprocess.Popen', side_effect=AssertionError('No live commands'))):
            item.start(); self.addCleanup(item.stop)
        self.store = LockedMemoryStore(); self.backend = MemoryBackend(self.store)
        self.control = Controller(self.backend, self.store)
        self.children = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid in self.children:
            try:
                # Only exact test children, never process names or stored PIDs.
                if os.waitpid(pid, os.WNOHANG) == (0, 0):
                    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
            except ChildProcessError: pass

    def held(self, seconds=None):
        """A different process owns the exact directory lock; pipe proves acquisition."""
        rd, wr = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(rd)
                fd = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(wr, b'1'); os.close(wr)
                if seconds is None:
                    signal.pause()
                else:
                    time.sleep(seconds)
                os.close(fd)
            finally: os._exit(0)
        self.children.append(pid); os.close(wr)
        self.assertEqual(os.read(rd, 1), b'1'); os.close(rd)
        return pid

    def assert_off(self):
        self.assertIsNone(self.store.data)
        self.assertIsNone(self.backend.i); self.assertIsNone(self.backend.p); self.assertIsNone(self.backend.t)
        self.assertEqual(self.backend.a, {policy.CELL_UUID: ['wwan0mbim0']})
        self.assertEqual(self.backend.rv, 'disabled'); self.assertTrue(self.backend.av)
        self.assertEqual(self.store.public['mode'], 'off')

    def invoke(self, action):
        with patch.object(helper, 'Store', return_value=self.store), \
             patch.object(helper, 'Backend', return_value=self.backend), \
             patch.object(helper.signal, 'signal'), patch.object(helper.signal, 'alarm'), \
             patch('resource.setrlimit'), patch('sys.stdout', new_callable=io.StringIO) as output:
            mask = os.umask(0o077)
            try: rc = helper.main([action])
            finally: os.umask(mask)
        return rc, json.loads(output.getvalue())

    def test_immediately_available_no_poll_sleep(self):
        with patch.object(state.time, 'sleep', side_effect=AssertionError('No contention')):
            with self.store.locked(): pass

    def test_waits_for_supervisor_then_acquires(self):
        self.held(.15)
        with self.store.locked(timeout=1): pass

    def test_exact_observed_busy_after_activation_then_off_recovers(self):
        # The old nonblocking helper would reject both doctor and OFF during a
        # supervisor check, despite NM having successfully activated the AP.
        with self.store.locked(): self.control.start('internet')
        self.held(.2)
        with self.assertRaisesRegex(rb.OperationError, 'BUSY:'):
            with self.store.locked(timeout=0): self.fail('Old path must reject')
        rc, value = self.invoke('off')
        self.assertEqual(rc, 0); self.assertTrue(value['ok']); self.assert_off()

    def test_timeout_is_bounded_and_has_kernel_owner(self):
        pid = self.held()
        begin = time.monotonic()
        with self.assertRaisesRegex(rb.OperationError, 'kernel_pid=' + str(pid)):
            with self.store.locked(timeout=.1): self.fail('Lock stolen')
        self.assertLess(time.monotonic() - begin, 1)
        self.assertGreaterEqual(time.monotonic() - begin, .09)

    def test_second_internet_busy_without_mutating(self):
        self.held()
        with patch.object(helper, 'LOCK_WAIT', 0): rc, value = self.invoke('internet')
        self.assertEqual(rc, 1); self.assertIn('BUSY:', value['error'])
        self.assertEqual(self.backend.calls, [])

    def test_concurrent_local_busy_without_mutating(self):
        self.held()
        with patch.object(helper, 'LOCK_WAIT', 0): rc, value = self.invoke('local')
        self.assertEqual(rc, 1); self.assertIn('BUSY:', value['error'])
        self.assertEqual(self.backend.calls, [])

    def test_external_off_respects_live_foreign_operation(self):
        self.held()
        with patch.object(helper, 'RECOVERY_LOCK_WAIT', .1): rc, value = self.invoke('off')
        self.assertEqual(rc, 1); self.assertIn('BUSY:', value['error'])
        self.assertEqual(self.backend.calls, [])

    def test_live_lock_never_unlinked_or_stolen(self):
        self.held(); before = self.private.stat().st_ino
        with self.assertRaises(rb.OperationError):
            with self.store.locked(timeout=0): pass
        self.assertEqual(before, self.private.stat().st_ino)

    def test_dead_owner_crash_releases_kernel_lock(self):
        pid = self.held(); before = self.private.stat().st_ino
        os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        with self.store.locked(timeout=0): pass
        self.assertEqual(before, self.private.stat().st_ino)

    def test_stale_lock_metadata_does_not_block(self):
        (self.private / 'operation-lock.json').write_text('{"pid":99999999}')
        with self.store.locked(timeout=0): pass
        self.assertTrue((self.private / 'operation-lock.json').exists())

    def test_reused_pid_is_not_cleanup_authority(self):
        # Even a currently alive PID in a stale file grants no lock ownership.
        (self.private / 'operation-lock.json').write_text(json.dumps({'pid': os.getpid()}))
        with self.store.locked(timeout=0): pass

    def test_exception_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with self.store.locked(): raise RuntimeError('fixture')
        with self.store.locked(timeout=0): pass

    def test_no_same_pid_public_bypass(self):
        with self.store.locked():
            with self.assertRaises(rb.OperationError):
                with self.store.locked(timeout=0): pass

    def test_exact_requested_activation_failure_internal_off_no_second_lock(self):
        self.backend.fail, self.backend.fault_after = 'activate', True
        with patch.object(self.store, 'locked', wraps=self.store.locked) as calls:
            rc, value = self.invoke('internet')
        self.assertEqual(rc, 1); self.assertNotIn('BUSY:', value['error'])
        self.assertEqual(calls.call_count, 1); self.assert_off()

    def test_failure_before_ap_creation(self):
        self.backend.fail = 'watch'
        self.assertEqual(self.invoke('internet')[0], 1); self.assert_off()

    def test_failure_after_ap_creation(self):
        self.backend.fail, self.backend.fault_after = 'interface', True
        self.assertEqual(self.invoke('internet')[0], 1); self.assert_off()

    def test_failure_after_firewall_creation(self):
        self.backend.fail, self.backend.fault_after = 'guard_blocked', True
        self.assertEqual(self.invoke('internet')[0], 1); self.assert_off()

    def test_sigterm_internal_cleanup_releases_lock(self):
        with patch.object(self.backend, 'activate', side_effect=lambda o: helper.deadline(signal.SIGTERM, None)):
            rc, value = self.invoke('internet')
        self.assertEqual(rc, 1); self.assertIn('OPERATION_INTERRUPTED', value['error']); self.assert_off()
        with self.store.locked(timeout=0): pass

    def test_internal_cleanup_twice_without_reentry(self):
        with self.store.locked():
            self.control.start('internet'); self.control.stop()
            previous = list(self.backend.calls); self.control.stop()
        self.assertEqual(previous, self.backend.calls); self.assert_off()

    def test_rollback_twice(self):
        with self.store.locked():
            self.control.start('internet')
            rollback = rb.Rollback(self.control.owner(self.store.data), self.backend, emit=lambda _: None)
            rollback.execute(apply=True); previous = list(self.backend.calls)
            rollback.execute(apply=True); self.assertEqual(previous, self.backend.calls)
            self.control.stop()
        self.assert_off()

    def test_stale_valid_session_without_live_lock_is_cleaned(self):
        self.store.save(self.control.new_state('internet'))
        self.assertEqual(self.invoke('off')[0], 0); self.assert_off()

    def test_supervisor_skips_instead_of_waiting(self):
        self.held()
        with patch.object(helper, 'Store', return_value=self.store), \
             patch.object(helper, 'Backend', return_value=self.backend), \
             patch.object(helper.time, 'sleep', side_effect=InterruptedError('end tick')):
            with self.assertRaises(InterruptedError): helper.watch()
        self.assertEqual(self.backend.calls, [])

    def test_invalid_timeouts_refused(self):
        for value in (-1, 31, float('inf'), float('nan'), '1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with self.store.locked(timeout=value): pass

    def test_lock_fd_not_inherited_by_exec(self):
        original = state.fcntl.flock
        flags = []
        def inspect(fd, op):
            flags.append(os.get_inheritable(fd)); return original(fd, op)
        with patch.object(state.fcntl, 'flock', side_effect=inspect):
            with self.store.locked(): pass
        self.assertEqual(flags, [False])


if __name__ == '__main__': unittest.main()
