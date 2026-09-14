"""Production lifecycle/security tests; no live network commands."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from aag_hotspot import ownership as rb
from aag_hotspot import policy
from aag_hotspot.backend import Backend
from aag_hotspot.controller import Controller
from aag_hotspot.state import owner_for, atomic_json
from aag_hotspot import client, helper
from aag_hotspot.cli import main as cli_main


class MemoryStore:
    boot_id = 'f0000005-0000-4000-8000-000000000005'
    def __init__(self): self.data = None; self.public = None; self.history = []
    def load(self): return copy.deepcopy(self.data)
    def save(self, value):
        owner_for(value, self.boot_id)
        self.data = copy.deepcopy(value)
        self.history.append(copy.deepcopy(value))
    def clear(self): self.data = None
    def configured(self): return True
    def password(self): return 'fixture-only-password'
    def publish(self, value): self.public = copy.deepcopy(value)


class MemoryBackend:
    def __init__(self, store):
        self.store = store
        self.p = self.i = self.t = None
        self.a = {policy.CELL_UUID: ['wwan0mbim0']}
        self.rv, self.av = 'disabled', True
        self.idle = True
        self.uplink = 'wwan0'
        self.calls = []
        self.fail = None
        self.fault_after = False
        self.digest = 'a' * 64
        self.leftover = False
    def event(self, name):
        self.calls.append(name)
        if self.fail == name and not self.fault_after:
            self.fail = None
            raise rb.OperationError('injected ' + name)
    def after(self, name):
        if self.fail == name and self.fault_after:
            self.fail = None
            raise rb.OperationError('injected after ' + name)
    def profiles(self): return set(rb.PROTECTED_UUIDS)
    def links(self): return [{'ifname': policy.STA, 'address': '02:00:00:00:10:01'}, {'ifname': 'wwan0'}]
    def radio(self): return self.rv
    def autoconnect(self): return self.av
    def wifi_idle(self): return self.idle
    def profile(self, _): return copy.deepcopy(self.p)
    def interface(self, _): return copy.deepcopy(self.i)
    def table(self, _): return copy.deepcopy(self.t)
    def active(self): return copy.deepcopy(self.a)
    def nm_rules_remain(self, _): return self.leftover
    def route_source(self): return self.uplink
    def clients(self, _): return 0
    def client_snapshot(self, _):
        return {'clients': 0, 'client_count': 0, 'client_details': [], 'client_data_status': 'OK'}
    def cellular(self):
        if self.uplink != 'wwan0': raise rb.OperationError('CELLULAR_REQUIRED')
    def preflight(self, mode):
        self.event('preflight')
        if not self.idle: raise rb.OperationError('WIFI_STA_UNVALIDATED')
        if mode == 'internet': self.cellular()
    def arm_watch(self): self.event('watch'); self.after('watch')
    def planned_absent(self, _):
        if self.p or self.i or self.t: raise rb.SafetyError('occupied')
    def guard(self, o, mode, create=False):
        self.event('guard_' + mode)
        if not create and (not self.t or self.t['comment'] != o.marker): raise rb.SafetyError('foreign guard')
        policy.nft_program(o, mode, create)
        self.t = {'family': 'inet', 'name': o.table, 'comment': o.marker, 'handle': 88}
        self.digest = {'local': 'a', 'internet': 'b', 'blocked': 'c'}[mode] * 64
        self.after('guard_' + mode)
        return 88, self.digest
    def create_interface(self, o):
        self.event('interface')
        assert self.rv == 'disabled' and self.store.data['radio_touched']
        self.i = {'name': o.vif, 'mac': o.mac, 'phy': 0, 'mode': 'AP', 'ifindex': 70}
        self.after('interface')
        return 70
    def add_profile(self, o, password):
        self.event('profile')
        self.p = {'uuid': o.profile_uuid, 'name': o.profile_name, 'type': '802-11-wireless',
                  'interface': o.vif, 'autoconnect': 'no', 'mode': 'ap'}
        self.after('profile')
    def activate(self, o):
        self.event('activate')
        self.a[o.profile_uuid] = [o.vif]
        self.after('activate')
    def wait_device_ready(self, o):
        self.event('readiness')
        assert self.rv == 'enabled' and self.i['name'] == o.vif
        self.after('readiness')
    def healthy(self, o, mode, digest):
        self.event('healthy')
        rb.Rollback(o, self).inspect()
        if self.a.get(o.profile_uuid) != [o.vif] or digest != self.digest: raise rb.OperationError('unhealthy')
        if mode == 'internet': self.cellular()
        self.after('healthy')
    def remove_lease(self, _): self.event('lease')
    def run(self, argv):
        o = owner_for(self.store.data, self.store.boot_id)
        allowed = {
            'down': ['/usr/bin/nmcli', '--wait', '15', 'connection', 'down', 'uuid', o.profile_uuid],
            'delete_profile': ['/usr/bin/nmcli', '--wait', '15', 'connection', 'delete', 'uuid', o.profile_uuid],
            'delete_iface': ['/usr/sbin/iw', 'dev', o.vif, 'del'],
            'delete_table': ['/usr/sbin/nft', 'delete', 'table', 'inet', o.table],
            'radio_on': ['/usr/bin/nmcli', 'radio', 'wifi', 'on'],
            'radio_off': ['/usr/bin/nmcli', 'radio', 'wifi', 'off'],
            'auto_no': ['/usr/bin/nmcli', 'device', 'set', policy.STA, 'autoconnect', 'no'],
            'auto_yes': ['/usr/bin/nmcli', 'device', 'set', policy.STA, 'autoconnect', 'yes'],
        }
        name = next((k for k, v in allowed.items() if argv == v), None)
        if name is None: raise AssertionError('Unexpected mutation ' + repr(argv))
        self.event(name)
        if name == 'down': self.a.pop(o.profile_uuid, None)
        if name == 'delete_profile': self.p = None
        if name == 'delete_iface': self.i = None
        if name == 'delete_table': self.t = None
        if name.startswith('radio_'):
            assert self.store.data['radio_touched']
            self.rv = 'enabled' if name == 'radio_on' else 'disabled'
        if name.startswith('auto_'):
            assert self.store.data['auto_touched']
            self.av = name == 'auto_yes'
        self.after(name)
        return ''


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.backend = MemoryBackend(self.store)
        self.controller = Controller(self.backend, self.store)

    def assert_clean(self):
        b = self.backend
        self.assertIsNone(b.p); self.assertIsNone(b.i); self.assertIsNone(b.t)
        self.assertEqual(b.a, {policy.CELL_UUID: ['wwan0mbim0']})
        self.assertIsNone(self.store.data)
        self.assertEqual(b.rv, 'disabled'); self.assertTrue(b.av)

    def test_start_switch_and_repeated_off(self):
        self.controller.start('internet')
        uid = self.store.data['ownership']['resources']['profile_uuid']
        self.controller.start('local')
        self.assertEqual(self.store.data['mode'], 'local')
        self.assertEqual(self.store.data['ownership']['resources']['profile_uuid'], uid)
        self.controller.start('internet')
        self.controller.stop()
        n = len(self.backend.calls)
        self.controller.stop()
        self.assertEqual(n, len(self.backend.calls))
        self.assert_clean()

    def test_watchdog_precedes_network_and_guard_precedes_radio(self):
        self.controller.start('local')
        events = self.backend.calls
        self.assertLess(events.index('watch'), events.index('guard_blocked'))
        self.assertLess(events.index('guard_blocked'), events.index('auto_no'))
        self.assertLess(events.index('profile'), events.index('radio_on'))
        self.assertLess(events.index('radio_on'), events.index('readiness'))
        self.assertLess(events.index('readiness'), events.index('activate'))

    def test_failures_before_and_after_every_activation_step_cleanup(self):
        for name in ('watch', 'guard_blocked', 'auto_no', 'interface', 'profile', 'radio_on', 'readiness', 'activate', 'guard_local', 'healthy'):
            for after in (False, True):
                with self.subTest(step=name, after=after):
                    self.setUp()
                    self.backend.fail, self.backend.fault_after = name, after
                    with self.assertRaises(rb.OperationError): self.controller.start('local')
                    self.assert_clean()

    def test_start_preserves_original_enabled_idle_radio(self):
        self.backend.rv = 'enabled'
        self.controller.start('local')
        self.controller.stop()
        self.assertEqual(self.backend.rv, 'enabled')
        self.assertTrue(self.backend.av)

    def test_new_station_is_preserved_during_shutdown(self):
        self.controller.start('local')
        self.backend.idle = False
        with self.assertRaises(rb.OperationError): self.controller.stop()
        self.assertIsNone(self.backend.p); self.assertIsNone(self.backend.i)
        self.assertEqual(self.backend.rv, 'enabled')
        self.assertIsNotNone(self.store.data)
        self.backend.idle = True
        self.controller.stop()
        self.assert_clean()

    def test_station_uplink_or_missing_cellular_refuses_before_mutation(self):
        for uplink, idle in [('wlan0', False), ('tailscale0', True), (None, True), ('docker0', True)]:
            with self.subTest(uplink=uplink):
                self.setUp();self.backend.uplink = uplink;self.backend.idle = idle
                with self.assertRaises(rb.OperationError): self.controller.start('internet')
                self.assertIsNone(self.store.data)
                self.assertEqual(self.backend.calls, ['preflight'])

    def test_local_mode_without_uplink_and_downgrade_after_uplink_loss(self):
        self.backend.uplink = None
        self.controller.start('local')
        with self.assertRaises(rb.OperationError): self.controller.start('internet')
        self.assertEqual(self.store.data['mode'], 'local')
        self.backend.uplink = 'wwan0'
        self.controller.start('internet')
        self.backend.uplink = None
        self.controller.start('local')
        self.controller.stop()
        self.assert_clean()

    def test_failed_mode_transaction_shuts_down(self):
        self.controller.start('internet')
        self.backend.fail = 'guard_local'
        with self.assertRaises(rb.OperationError): self.controller.start('local')
        self.assert_clean()

    def test_interrupted_transition_watch_tick_cleans_up(self):
        self.controller.start('local')
        self.store.data['phase'] = 'switching'
        self.assertFalse(self.controller.tick())
        self.assert_clean()

    def test_watch_stops_internet_after_route_changes(self):
        self.controller.start('internet')
        self.backend.uplink = 'tailscale0'
        self.assertFalse(self.controller.tick())
        self.assert_clean()

    def test_unrelated_table_is_never_deleted(self):
        self.controller.start('local')
        self.backend.t['comment'] = 'belongs to someone else'
        events = list(self.backend.calls)
        with self.assertRaises(rb.SafetyError): self.controller.stop()
        self.assertEqual(events, self.backend.calls)

    def test_cleanup_failure_can_be_retried(self):
        for name in ('down', 'delete_profile', 'delete_iface', 'delete_table', 'radio_off', 'auto_yes'):
            with self.subTest(step=name):
                self.setUp();self.controller.start('local');self.backend.fail = name
                with self.assertRaises(rb.OperationError): self.controller.stop()
                self.assertIsNotNone(self.store.data)
                self.controller.stop();self.assert_clean()

    def test_nm_remnants_retain_guard(self):
        self.controller.start('local');self.backend.leftover = True
        with self.assertRaises(rb.OperationError): self.controller.stop()
        self.assertIsNotNone(self.backend.t)
        self.backend.leftover = False
        self.controller.stop();self.assert_clean()

    def test_secret_never_published(self):
        self.controller.start('local')
        self.assertNotIn(self.store.password(), json.dumps(self.store.public))
        self.assertNotIn(self.store.password(), json.dumps(self.store.history))

    def test_namespace_and_protected_uuid_checks(self):
        data = self.controller.new_state('local')
        owner = self.controller.owner(data)
        self.assertTrue(owner.profile_name.startswith('AAG Hotspot '))
        self.assertTrue(owner.vif.startswith('aaghp'))
        self.assertEqual(owner.table, 'aag_hotspot')
        data['ownership']['resources']['profile_uuid'] = policy.HOTSPOT_UUID
        with self.assertRaises(rb.SafetyError): self.controller.owner(data)

    def test_stale_boot_and_extra_schema_keys_refused(self):
        data = self.controller.new_state('local')
        with self.assertRaises(rb.SafetyError): owner_for(data, 'different boot')
        data['command'] = 'arbitrary'
        with self.assertRaises(rb.SafetyError): self.controller.owner(data)

    def test_local_dns_block_precedes_established_and_no_unconditional_accept(self):
        r = policy.rules('aaghp12345678', 'local')
        ingress = '\n'.join(r['input_guard'])
        self.assertLess(ingress.index('udp dport 53 counter drop'), ingress.index('ct state established'))
        self.assertTrue(all('aaghp12345678' in line for entries in r.values() for line in entries))
        forward_accepts = [x for x in r['forward_guard'] if x.endswith('accept')]
        self.assertEqual(len(forward_accepts), 1)
        self.assertIn('iifname "aaghp12345678" oifname "aaghp12345678" ip daddr 10.77.0.0/24', forward_accepts[0])
        self.assertIn('sport 53 counter drop', '\n'.join(r['output_guard']))

    def test_policy_rejects_injection_and_never_owns_nat(self):
        for name in ('wlan0', 'aaghp12345678; flush ruleset', 'docker0'):
            with self.assertRaises(ValueError): policy.rules(name, 'local')
        for mode in ('local', 'internet', 'blocked'):
            program = policy.nft_program(self.controller.owner(self.controller.new_state('local')), mode, True)
            self.assertNotIn('masquerade', program)
            self.assertNotIn('flush ruleset', program)
            self.assertNotIn('delete table', program)

    def test_atomic_public_permissions_do_not_inherit_private_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            old = os.umask(0o077)
            try: atomic_json(path, {'password': 'not-a-real-secret-fixture'}, 0o644)
            finally: os.umask(old)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_helper_rejects_extra_args_before_store_or_commands(self):
        with patch.object(helper, 'Store', side_effect=AssertionError('must not construct')), patch.object(helper.os, 'geteuid', return_value=0), patch('sys.stdout', new_callable=io.StringIO):
            for args in ([], ['internet', 'wlan0'], ['shell'], ['configure', 'secret'], ['--watch']):
                self.assertEqual(helper.main(args), 2)

    def test_cli_dry_run_never_invokes_helper(self):
        with patch.object(client, 'request', side_effect=AssertionError('unexpected helper')), patch('sys.stdout', new_callable=io.StringIO):
            for action in ('local', 'internet', 'off', 'configure'):
                self.assertEqual(cli_main([action, '--dry-run', '--json']), 0)

    def test_password_constraints(self):
        for value in ('short', 'a'*64, 'new\nline-secret', 'סיסמהעבריתארוכה', None):
            with self.assertRaises(ValueError): policy.validate_password(value)
        self.assertEqual(policy.validate_password('correct horse battery'), 'correct horse battery')


if __name__ == '__main__': unittest.main()
