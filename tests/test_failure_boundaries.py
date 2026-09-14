"""Credential, lifecycle and command failures with no real network side effects."""
import subprocess
import unittest
from unittest.mock import patch

from test_production import MemoryBackend, MemoryStore
from aag_hotspot import ownership as rb
from aag_hotspot.backend import Backend
from aag_hotspot.controller import Controller
from aag_hotspot.state import Store


class FailureBoundaryTests(unittest.TestCase):
    def test_absent_credentials_refuse_before_state_or_network_mutation(self):
        s = MemoryStore(); b = MemoryBackend(s)
        with patch.object(s, 'password', side_effect=FileNotFoundError):
            for mode in ('internet', 'local'):
                with self.assertRaises(FileNotFoundError): Controller(b, s).start(mode)
        self.assertEqual(b.calls, [])
        self.assertIsNone(s.data)

    def test_malformed_credential_schema_refuses_before_network(self):
        s = Store()
        for data in ({}, {'schema': True, 'password': 'fixture-only-password'},
                     {'schema': 2, 'password': 'fixture-only-password'},
                     {'schema': 1, 'password': 'short'},
                     {'schema': 1, 'password': 'fixture-only-password', 'command': 'bad'}):
            with self.subTest(data=data), patch('aag_hotspot.state.trusted_dir'), patch('aag_hotspot.state.secure_read', return_value=data):
                with self.assertRaises((rb.SafetyError, ValueError)): s.password()

    def test_repeated_active_mode_does_not_create_or_reactivate(self):
        for mode in ('internet', 'local'):
            with self.subTest(mode=mode):
                s = MemoryStore(); b = MemoryBackend(s); c = Controller(b, s)
                c.start(mode)
                before = c.owner(s.load())
                for _ in range(10): c.start(mode)
                self.assertEqual(c.owner(s.load()), before)
                self.assertEqual(b.calls.count('activate'), 1)
                self.assertEqual(b.calls.count('profile'), 1)
                self.assertEqual(b.calls.count('interface'), 1)
                c.stop()
                self.assertIsNone(s.load())

    def test_repeated_cross_mode_cycles_clean_every_session(self):
        s = MemoryStore(); b = MemoryBackend(s); c = Controller(b, s)
        for _ in range(12):
            for modes in (('internet',), ('local',), ('internet', 'local'), ('local', 'internet')):
                for mode in modes: c.start(mode)
                c.stop(); c.stop()
                self.assertIsNone(s.data)
                self.assertIsNone(b.p); self.assertIsNone(b.i); self.assertIsNone(b.t)
                self.assertEqual(b.rv, 'disabled'); self.assertTrue(b.av)
                self.assertEqual(len(b.a), 1)

    def test_incomplete_session_refuses_duplicate_activation_until_off(self):
        s = MemoryStore(); b = MemoryBackend(s); c = Controller(b, s)
        c.start('internet'); s.data['phase'] = 'starting'
        before = list(b.calls)
        with self.assertRaises(rb.OperationError): c.start('internet')
        self.assertEqual(before, b.calls)
        c.stop()
        self.assertIsNone(s.data)

    def test_atomic_firewall_failure_suppresses_private_command_output(self):
        b = Backend()
        private = 'fixture-secret-must-not-escape'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, private, private)):
            with self.assertRaises(rb.OperationError) as caught: b.nft('fixture')
        self.assertNotIn(private, str(caught.exception))

    def test_atomic_firewall_timeout_and_missing_binary_are_bounded(self):
        for failure in (OSError('fixture'), subprocess.TimeoutExpired(['nft'], 15)):
            with patch('subprocess.run', side_effect=failure) as run:
                with self.assertRaises(rb.OperationError): Backend().nft('fixture')
                self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_client_count_uses_only_actual_station_records(self):
        from aag_hotspot.clients import stations
        for output, count in [('', 0), ('Station 02:00:00:00:00:01 (on aaghp12345678)\n\tinactive time: 2 ms\n', 1),
                              ('Station 02:00:00:00:00:01 (on aaghp12345678)\nStation 02:00:00:00:00:02 (on aaghp12345678)\n', 2),
                              ]:
            self.assertEqual(len(stations(output, 'aaghp12345678')), count)
        with self.assertRaises(ValueError): stations('192.0.2.1 dev ignored STALE', 'aaghp12345678')


if __name__ == '__main__': unittest.main()
