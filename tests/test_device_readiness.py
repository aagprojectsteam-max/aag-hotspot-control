"""Production readiness polling with a fake clock/NM subprocess, never a live AP."""
import copy
import subprocess
import unittest
from unittest.mock import patch

from test_production import MemoryBackend, MemoryStore
from aag_hotspot.backend import Backend
from aag_hotspot.controller import Controller
from aag_hotspot import ownership as rb, policy


class Clock:
    def __init__(self): self.now = 0.0; self.sleeps = []
    def monotonic(self): return self.now
    def sleep(self, seconds):
        self.sleeps.append(seconds); self.now += seconds


class NM:
    """Only the three allowed read-only nmcli argv forms can be called."""
    def __init__(self, owner, frames):
        self.owner = owner; self.frames = frames; self.index = -1; self.calls = []
    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv == ['/usr/bin/nmcli', '-g', 'RUNNING,WIFI-HW,WIFI', 'general', 'status']:
            self.index += 1
            f = self.frames[min(self.index, len(self.frames) - 1)]
            if f.get('oserror'): raise OSError('fixture raw secret must not escape')
            if f.get('timeout'): raise subprocess.TimeoutExpired(argv, kwargs['timeout'], output='fixture-secret')
            out = f.get('general', 'running:enabled:enabled') + '\n'
            code = f.get('exit', 0)
        else:
            f = self.frames[min(self.index, len(self.frames) - 1)]; code = 0
            if argv == ['/usr/bin/nmcli', '-g', 'DEVICE', 'device', 'status']:
                names = [policy.STA, 'p2p-dev-' + policy.STA, 'p2p-dev-' + self.owner.vif, 'wwan0']
                if f.get('present', True): names.append(self.owner.vif)
                out = '\n'.join(names) + '\n'
            elif argv == ['/usr/bin/nmcli', '-g', 'GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.REASON,GENERAL.NM-MANAGED,GENERAL.AUTOCONNECT', 'device', 'show', self.owner.vif]:
                out = '\n'.join([f.get('device', self.owner.vif), f.get('type', 'wifi'),
                                  f.get('state', '30 (disconnected)'), f.get('reason', '0 (No reason given)'),
                                  f.get('managed', 'yes'), f.get('autoconnect', 'no')]) + '\n'
            else: raise AssertionError('Unexpected command; test forbids network mutations: ' + repr(argv))
        return subprocess.CompletedProcess(argv, code, out, 'fixture-secret-error-body')


class LifecycleBackend(MemoryBackend, Backend):
    # Exercise the actual wait implementation inside the actual controller.
    wait_device_ready = Backend.wait_device_ready


class DeviceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.memory = LifecycleBackend(self.store)
        self.controller = Controller(self.memory, self.store)
        self.owner = self.controller.owner(self.controller.new_state('internet'))
        self.clock = Clock()
        self.patches = [patch('aag_hotspot.backend.time.monotonic', self.clock.monotonic),
                        patch('aag_hotspot.backend.time.sleep', self.clock.sleep)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def wait(self, frames, backend=None):
        nm = NM(self.owner, frames)
        with patch('aag_hotspot.backend.subprocess.run', nm.run):
            (backend or Backend()).wait_device_ready(self.owner)
        return nm

    def assert_clean(self, radio='disabled'):
        self.assertIsNone(self.store.data)
        self.assertIsNone(self.memory.p); self.assertIsNone(self.memory.i); self.assertIsNone(self.memory.t)
        self.assertEqual(self.memory.a, {policy.CELL_UUID: ['wwan0mbim0']})
        self.assertEqual(self.memory.rv, radio); self.assertTrue(self.memory.av)

    def test_immediately_ready_returns_without_delay_or_writes(self):
        nm = self.wait([{}])
        self.assertEqual(len(nm.calls), 3)
        self.assertEqual(self.clock.sleeps, [])

    def test_unavailable_then_ready_waits_for_state_not_elapsed_delay(self):
        nm = self.wait([{'state': '20 (unavailable)'}, {'state': '20 (unavailable)'}, {}])
        self.assertEqual(nm.index, 2)
        self.assertEqual(self.clock.sleeps, [0.25, 0.25])

    def test_late_discovery_and_unmanaged_state_are_pending(self):
        nm = self.wait([{'present': False}, {'state': '10 (unmanaged)', 'managed': 'no'}, {}])
        self.assertEqual(nm.index, 2)

    def test_idle_p2p_sibling_cannot_substitute_for_owned_ap(self):
        with self.assertRaisesRegex(rb.OperationError, 'READINESS_TIMEOUT.*not-discovered'):
            self.wait([{'present': False}])
        self.assertEqual(self.clock.now, Backend.READINESS_TIMEOUT)

    def test_timeout_reports_last_numeric_state_reason_and_bounds_polling(self):
        with self.assertRaisesRegex(rb.OperationError, r'READINESS_TIMEOUT: 10s; .*state=20 reason=10 managed=yes'):
            self.wait([{'state': '20 (unavailable)', 'reason': '10 (Supplicant failed)'}])
        self.assertEqual(self.clock.now, 10.0)
        self.assertEqual(len(self.clock.sleeps), 40)

    def test_hardware_and_software_rfkill_fail_without_wait_or_unblock(self):
        for general in ('running:disabled:enabled', 'running:enabled:disabled'):
            with self.subTest(general=general), self.assertRaisesRegex(rb.OperationError, 'RFKILL_BLOCKED'):
                self.wait([{'general': general}])
        self.assertEqual(self.clock.sleeps, [])

    def test_rfkill_becoming_blocked_during_wait_aborts(self):
        with self.assertRaisesRegex(rb.OperationError, 'RFKILL_BLOCKED'):
            self.wait([{'state': '20 (unavailable)'}, {'general': 'running:disabled:disabled'}])
        self.assertEqual(self.clock.sleeps, [0.25])

    def test_nm_unavailable_or_unresponsive_fails_without_raw_error_leak(self):
        for frame in ({'exit': 8}, {'general': 'not running:enabled:enabled'}, {'oserror': True}, {'timeout': True}):
            with self.subTest(frame=frame), self.assertRaises(rb.OperationError) as raised:
                self.wait([frame])
            self.assertIn('NM_READINESS_UNAVAILABLE', str(raised.exception))
            self.assertNotIn('secret', str(raised.exception))
        self.assertEqual(self.clock.sleeps, [])

    def test_managed_flag_required_even_when_state_is_disconnected(self):
        self.wait([{'managed': 'no'}, {}])
        self.assertEqual(self.clock.sleeps, [0.25])

    def test_busy_failed_foreign_or_autoconnect_changed_device_refused(self):
        frames = [{'state': '40 (prepare)'}, {'state': '100 (activated)'}, {'state': '120 (failed)'},
                  {'device': policy.STA}, {'type': 'wifi-p2p'}, {'autoconnect': 'yes'}, {'state': 'invalid'}]
        for frame in frames:
            with self.subTest(frame=frame), self.assertRaises((rb.OperationError, rb.SafetyError)):
                self.wait([frame])

    def test_repeated_ready_invocation_is_read_only_and_immediate(self):
        nm = NM(self.owner, [{}])
        with patch('aag_hotspot.backend.subprocess.run', nm.run):
            b = Backend(); b.wait_device_ready(self.owner); b.wait_device_ready(self.owner)
        self.assertEqual(len(nm.calls), 6)
        self.assertEqual(self.clock.sleeps, [])

    def test_each_probe_timeout_is_capped_by_remaining_shared_deadline(self):
        def probe(argv, **kw):
            self.assertAlmostEqual(kw['timeout'], 0.125)
            self.assertEqual(kw['env']['LC_ALL'], 'C')
            self.clock.now += kw['timeout']
            raise subprocess.TimeoutExpired(argv, kw['timeout'])
        with patch('aag_hotspot.backend.subprocess.run', probe), self.assertRaises(TimeoutError):
            Backend()._readiness_read(['/usr/bin/nmcli'], 0.125)
        with patch('aag_hotspot.backend.subprocess.run') as unused, self.assertRaises(TimeoutError):
            Backend()._readiness_read(['/usr/bin/nmcli'], 0.125)
        unused.assert_not_called()

    def test_probe_completion_after_deadline_cannot_report_ready(self):
        nm = NM(self.owner, [{}])
        def slow(*args, **kwargs):
            answer = nm.run(*args, **kwargs)
            if len(nm.calls) == 3: self.clock.now = 10.0
            return answer
        with patch('aag_hotspot.backend.subprocess.run', slow), self.assertRaisesRegex(rb.OperationError, 'READINESS_TIMEOUT'):
            Backend().wait_device_ready(self.owner)

    def lifecycle_nm(self, frames):
        nm = NM(self.owner, frames)
        def probe(*args, **kwargs):
            nm.owner = self.controller.owner(self.store.data)
            return nm.run(*args, **kwargs)
        return patch('aag_hotspot.backend.subprocess.run', probe)

    def test_timeout_after_partial_creation_rolls_back_and_restores_both_radio_baselines(self):
        for radio in ('disabled', 'enabled'):
            with self.subTest(radio=radio):
                self.memory.rv = radio
                with self.lifecycle_nm([{'state': '20 (unavailable)'}]), self.assertRaisesRegex(rb.OperationError, 'READINESS_TIMEOUT'):
                    self.controller.start('internet')
                self.assertNotIn('activate', self.memory.calls)
                self.assert_clean(radio)
                self.controller.stop(); self.assert_clean(radio)

    def test_nm_failure_retains_failed_cleanup_receipt_for_repeat_off(self):
        self.memory.fail = 'delete_profile'
        with self.lifecycle_nm([{'exit': 8}]), self.assertRaises(rb.OperationError):
            self.controller.start('internet')
        self.assertIsNotNone(self.store.data)
        self.assertEqual(self.store.public['error'], 'RECOVERY_REQUIRED')
        self.assertIsNotNone(self.memory.t)
        self.controller.stop(); self.assert_clean()

    def test_repeated_start_does_not_wait_or_activate_again(self):
        with self.lifecycle_nm([{'state': '20 (unavailable)'}, {}]):
            self.controller.start('internet')
        with patch('aag_hotspot.backend.subprocess.run', side_effect=AssertionError('Unexpected second readiness wait')):
            self.controller.start('internet')
        self.assertEqual(self.memory.calls.count('activate'), 1)
        self.controller.stop(); self.assert_clean()

    def test_cellular_route_change_during_wait_refuses_before_activation(self):
        nm = NM(self.owner, [{}])
        def probe(*args, **kwargs):
            nm.owner = self.controller.owner(self.store.data)
            value = nm.run(*args, **kwargs)
            if len(nm.calls) == 3: self.memory.uplink = 'tailscale0'
            return value
        with patch('aag_hotspot.backend.subprocess.run', probe), self.assertRaisesRegex(rb.OperationError, 'CELLULAR_REQUIRED'):
            self.controller.start('internet')
        self.assertNotIn('activate', self.memory.calls)
        self.assert_clean()

    def test_profile_binding_changed_during_wait_is_not_activated_or_deleted(self):
        nm = NM(self.owner, [{}])
        def probe(*args, **kwargs):
            nm.owner = self.controller.owner(self.store.data)
            value = nm.run(*args, **kwargs)
            if len(nm.calls) == 3: self.memory.p['interface'] = policy.STA
            return value
        with patch('aag_hotspot.backend.subprocess.run', probe), self.assertRaises(rb.SafetyError):
            self.controller.start('internet')
        self.assertNotIn('activate', self.memory.calls)
        self.assertNotIn('delete_profile', self.memory.calls)
        self.assertIsNotNone(self.store.data)


if __name__ == '__main__': unittest.main()
