"""Diagnostic failures must not masquerade as a live AP or successful action."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot import client, cli
from aag_hotspot.gui import presentation, error_message


class DiagnosticTests(unittest.TestCase):
    def test_helper_malformed_or_failed_success_response_is_rejected(self):
        for data, code in [({}, 0), ({'ok': 'true'}, 0), ({'ok': True}, 1), ([], 0), (None, 0),
                           ({'ok': True, 'status': 'invalid'}, 0), ({'ok': True, 'checks': None}, 0),
                           ({'ok': False, 'error': []}, 1)]:
            with self.subTest(data=data, code=code), patch.object(Path, 'is_file', return_value=True), patch.object(
                    client.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, json.dumps(data), '')):
                self.assertEqual(client.request('off'), {'ok': False, 'error': 'HELPER_PROTOCOL_ERROR'})

    def test_helper_failure_and_success_have_boolean_result(self):
        for data, code in [({'ok': False, 'error': 'CELLULAR_REQUIRED'}, 1), ({'ok': True, 'status': {'mode': 'off'}}, 0)]:
            with patch.object(Path, 'is_file', return_value=True), patch.object(client.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], code, json.dumps(data), '')):
                self.assertEqual(client.request('off'), data)

    def test_transport_errors_never_expose_subprocess_output(self):
        cases = [(subprocess.TimeoutExpired(['pkexec'], 180), 'TIMEOUT_RECOVERY_PENDING'),
                 (OSError('fixture private detail'), 'HELPER_UNAVAILABLE')]
        for exc, expected in cases:
            with patch.object(Path, 'is_file', return_value=True), patch.object(client.subprocess, 'run', side_effect=exc):
                self.assertEqual(client.request('off'), {'ok': False, 'error': expected})

    def test_authentication_denial_uses_controlled_error(self):
        for code in (126, 127):
            with patch.object(Path, 'is_file', return_value=True), patch.object(client.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], code, '', 'fixture private stderr')):
                self.assertEqual(client.request('off')['error'], 'AUTHENTICATION_CANCELLED_OR_DENIED')

    def test_unexpected_route_shape_reports_no_uplink(self):
        for route in ('null', '{}', '[null]', '[1]', '[]', 'malformed'):
            with self.subTest(route=route), patch.object(Path, 'lstat', side_effect=FileNotFoundError), patch.object(
                    client, 'probe', return_value={'ok': True, 'stdout': route}):
                self.assertIsNone(client.status()['uplink'])

    def test_stale_gui_status_does_not_claim_active_or_invent_clients(self):
        for health in ('UNKNOWN', 'ERROR'):
            value = presentation({'mode': 'internet', 'phase': 'active', 'health': health, 'clients': 2})
            self.assertEqual(value['mode'], 'לא ניתן לאמת את מצב הרשת')
            self.assertEqual(value['clients'], 'לא ידוע')

    def test_gui_boolean_client_count_is_not_a_station_count(self):
        self.assertEqual(presentation({'clients': True})['clients'], 'לא ידוע')

    def test_gui_readiness_errors_have_specific_hebrew_guidance(self):
        cases = [('NM_DEVICE_RFKILL_BLOCKED', 'חסום'), ('Wi-Fi hardware radio is blocked', 'חסום'),
                 ('NM_DEVICE_READINESS_TIMEOUT', 'בזמן'), ('NM_READINESS_UNAVAILABLE', 'NetworkManager'),
                 ('TIMEOUT_RECOVERY_PENDING', 'כיבוי'), ('HELPER_UNAVAILABLE', 'התקנה')]
        for code, word in cases:
            with self.subTest(code=code): self.assertIn(word, error_message(code))

    def test_doctor_exit_code_reflects_nested_status_health(self):
        for health in ('ERROR', 'UNKNOWN', 'NOT_INSTALLED'):
            with patch.object(client, 'doctor', return_value={'status': {'health': health}, 'checks': {}}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['doctor', '--json']), 1)

    def test_status_not_installed_is_nonzero(self):
        with patch.object(client, 'status', return_value={'health': 'NOT_INSTALLED'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['status', '--json']), 1)

    def test_unconfigured_idle_doctor_is_useful_and_read_only(self):
        with patch.object(client, 'doctor', return_value={'status': {'health': 'OK'}, 'checks': {'password_configured': False}}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['doctor', '--json']), 0)


if __name__ == '__main__': unittest.main()
