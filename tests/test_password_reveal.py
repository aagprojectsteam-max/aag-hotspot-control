"""Secret read tests use invented credentials and never the host secret."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot import client, helper, state

SECRET = 'synthetic-test-password'


class RevealTests(unittest.TestCase):
    def test_helper_reads_without_backend_lock_or_publication_in_every_mode(self):
        for mode in ('off', 'internet', 'local'):
            store = Mock(); store.password.return_value = SECRET
            output = io.StringIO(); output.fileno = lambda: 1
            with patch.object(helper.os, 'geteuid', return_value=0), patch.object(helper, 'Store', return_value=store), \
                 patch.object(helper, 'Backend') as backend, patch.object(helper, 'Controller') as controller, \
                 patch.object(helper.os, 'fstat', return_value=Mock(st_mode=stat.S_IFIFO)), \
                 patch('sys.stdout', output):
                self.assertEqual(helper.main(['reveal-password']), 0)
            self.assertEqual(output.getvalue(), SECRET)
            self.assertEqual(store.mock_calls, [unittest.mock.call.password()])
            backend.assert_not_called(); controller.assert_not_called()

    def test_secret_refused_to_terminal_or_regular_file(self):
        for kind in (stat.S_IFREG, stat.S_IFCHR):
            with patch.object(helper.os, 'fstat', return_value=Mock(st_mode=kind)), \
                 patch.object(helper, 'Store') as store:
                self.assertEqual(helper.reveal_password(), 1)
                store.assert_not_called()

    def test_missing_malformed_and_exception_bodies_never_escape(self):
        for failure in (FileNotFoundError(SECRET), ValueError(SECRET), RuntimeError(SECRET)):
            output = io.StringIO(); output.fileno = lambda: 1
            with patch.object(helper, 'Store') as store, patch('sys.stdout', output), \
                 patch.object(helper.os, 'fstat', return_value=Mock(st_mode=stat.S_IFIFO)):
                store.return_value.password.side_effect = failure
                self.assertEqual(helper.reveal_password(), 1)
            self.assertEqual(output.getvalue(), '')

    def test_actual_credential_schema_validation_for_reveal(self):
        for data in ({}, {'schema': 1, 'password': 'short'}, {'schema': 2, 'password': SECRET},
                     {'schema': 1, 'password': SECRET, SECRET: 'unexpected'}):
            output = io.StringIO(); output.fileno = lambda: 1
            with patch('aag_hotspot.state.trusted_dir'), patch('aag_hotspot.state.secure_read', return_value=data), \
                 patch.object(helper.os, 'fstat', return_value=Mock(st_mode=stat.S_IFIFO)), patch('sys.stdout', output):
                self.assertEqual(helper.reveal_password(), 1)
            self.assertEqual(output.getvalue(), '')

    def test_transport_fixed_command_and_private_pipe(self):
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, SECRET.encode())) as run:
            for _ in range(5):
                result = client.reveal_password()
                self.assertEqual(result.pop('secret'), bytearray(SECRET.encode()))
                self.assertEqual(result, {'ok': True})
            self.assertEqual(run.call_args.args[0], ['/usr/bin/pkexec', client.HELPER, 'reveal-password'])
            self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs['stdout'], subprocess.PIPE)
            self.assertEqual(run.call_args.kwargs['timeout'], 120)

    def test_cancel_deny_and_helper_failures_are_sanitized(self):
        for code in (126, 127, 1, 2):
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], code, SECRET.encode(), SECRET.encode())):
                result = client.reveal_password()
            self.assertFalse(result['ok']); self.assertNotIn(SECRET, str(result))
            self.assertEqual(result['error'], 'AUTHENTICATION_CANCELLED_OR_DENIED' if code in (126,127) else 'SECRET_UNAVAILABLE')
        for data in (b'', b'x', b'\xff'*12, b'wrong\nprotocol', b'a'*64):
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, data)):
                self.assertEqual(client.reveal_password(), {'ok': False, 'error': 'SECRET_UNAVAILABLE'})
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['fixture'], 120, output=SECRET)):
            self.assertNotIn(SECRET, str(client.reveal_password()))

    def test_no_secret_action_on_generic_transport_or_inspection(self):
        with self.assertRaises(ValueError): client.request('reveal-password')
        with patch.object(client, 'reveal_password', side_effect=AssertionError('unexpected')):
            self.assertNotIn(SECRET, json.dumps(client.status()))
            self.assertNotIn(SECRET, json.dumps(client.doctor()))


if __name__ == '__main__': unittest.main()
