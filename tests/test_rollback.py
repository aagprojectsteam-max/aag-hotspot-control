"""Failure-path tests with an in-memory network; never create interfaces/rules."""
import copy
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from aag_hotspot import ownership as rb
BOOT = "f0000005-0000-4000-8000-000000000005"


def manifest():
    return {"schema": 1, "test_id": "f0000002-0000-4000-8000-000000000002", "boot_id": BOOT,
            "baseline": {"profile_uuids": sorted(rb.PROTECTED_UUIDS),
                         "interface_names": [rb.STA, "wwan0", "tailscale0", "docker0"],
                         "interface_macs": ["02:00:00:00:10:01"],
                         "wifi_radio": "disabled", "sta_autoconnect": True},
            "resources": {"profile_uuid": "f0000004-0000-4000-8000-000000000004",
                          "vif_ifindex": 70, "nft_handle": 88},
            "changes": {"wifi_radio_enabled": False, "sta_autoconnect_disabled": False}}


class FakeBackend:
    def __init__(self, owner, populated=True):
        self.o = owner
        self.p = {"uuid": owner.profile_uuid, "name": owner.profile_name,
                  "type": "802-11-wireless", "interface": owner.vif,
                  "autoconnect": "no", "mode": "ap"} if populated else None
        self.i = {"name": owner.vif, "mac": owner.mac, "ifindex": 70,
                  "phy": 0, "mode": "AP"} if populated else None
        self.t = {"family": "inet", "name": owner.table, "comment": owner.marker,
                  "handle": 88} if populated else None
        self.a = {owner.profile_uuid: [owner.vif]} if populated else {}
        self.radio_value, self.auto_value, self.idle = "enabled", False, True
        self.leftover = False
        self.fail = None
        self.calls = []
        # Unrelated objects must never appear in mutation commands.
        self.protected = {"profiles": sorted(rb.PROTECTED_UUIDS), "docker": ["docker0", "br-existing"],
                          "tailscale": "tailscale0", "modem": "wwan0", "routes": ["default wwan0"]}

    def profile(self, _): return copy.deepcopy(self.p)
    def interface(self, _): return copy.deepcopy(self.i)
    def table(self, _): return copy.deepcopy(self.t)
    def active(self): return copy.deepcopy(self.a)
    def nm_rules_remain(self, _): return self.leftover
    def radio(self): return self.radio_value
    def autoconnect(self): return self.auto_value
    def wifi_idle(self): return self.idle

    def run(self, argv):
        commands = {
            "down": ["/usr/bin/nmcli", "--wait", "15", "connection", "down", "uuid", self.o.profile_uuid],
            "delete_profile": ["/usr/bin/nmcli", "--wait", "15", "connection", "delete", "uuid", self.o.profile_uuid],
            "delete_iface": ["/usr/sbin/iw", "dev", self.o.vif, "del"],
            "delete_table": ["/usr/sbin/nft", "delete", "table", "inet", self.o.table],
            "radio_off": ["/usr/bin/nmcli", "radio", "wifi", "off"],
            "autoconnect_yes": ["/usr/bin/nmcli", "device", "set", rb.STA, "autoconnect", "yes"],
        }
        event = next((key for key, command in commands.items() if command == argv), None)
        if event is None:
            raise AssertionError("Unexpected mutation: " + repr(argv))
        self.calls.append(event)
        if self.fail == event:
            raise rb.OperationError("simulated command failure")
        if event == "down": self.a.pop(self.o.profile_uuid, None)
        if event == "delete_profile": self.p = None
        if event == "delete_iface": self.i = None
        if event == "delete_table": self.t = None
        if event == "radio_off": self.radio_value = "disabled"
        if event == "autoconnect_yes": self.auto_value = True
        return ""


class RollbackSafetyTests(unittest.TestCase):
    def setUp(self):
        self.data = manifest()
        self.owner = rb.validate_manifest(self.data, BOOT)
        self.backend = FakeBackend(self.owner)
        self.engine = rb.Rollback(self.owner, self.backend, lambda _: None)

    def test_dry_run_is_read_only_with_active_test(self):
        before = copy.deepcopy(vars(self.backend))
        self.engine.execute()
        self.assertEqual(vars(self.backend), before)

    def test_cleanup_order_protected_objects_and_idempotence(self):
        protected = copy.deepcopy(self.backend.protected)
        self.engine.execute(apply=True)
        self.assertEqual(self.backend.calls, ["down", "delete_profile", "delete_iface", "delete_table"])
        self.assertEqual(self.backend.protected, protected)
        self.engine.execute(apply=True)
        self.assertEqual(self.backend.calls, ["down", "delete_profile", "delete_iface", "delete_table"])

    def test_registered_but_nothing_created_is_noop(self):
        b = FakeBackend(self.owner, populated=False)
        rb.Rollback(self.owner, b, lambda _: None).execute(apply=True)
        self.assertEqual(b.calls, [])

    def test_all_partial_creation_combinations(self):
        for bits in range(8):
            with self.subTest(bits=bits):
                b = FakeBackend(self.owner)
                b.a = {}
                if not bits & 1: b.p = None
                if not bits & 2: b.i = None
                if not bits & 4: b.t = None
                rb.Rollback(self.owner, b, lambda _: None).execute(apply=True)
                self.assertIsNone(b.p); self.assertIsNone(b.i); self.assertIsNone(b.t)

    def test_crash_before_receipt_recorded(self):
        self.data["resources"]["vif_ifindex"] = None
        self.data["resources"]["nft_handle"] = None
        o = rb.validate_manifest(self.data, BOOT)
        b = FakeBackend(o)
        rb.Rollback(o, b, lambda _: None).execute(apply=True)
        self.assertEqual(b.calls[-1], "delete_table")

    def test_every_failed_cleanup_stage_can_be_retried(self):
        for stage in ["down", "delete_profile", "delete_iface", "delete_table"]:
            with self.subTest(stage=stage):
                b = FakeBackend(self.owner); b.fail = stage
                engine = rb.Rollback(self.owner, b, lambda _: None)
                with self.assertRaises(rb.OperationError): engine.execute(apply=True)
                self.assertIsNotNone(b.t)
                b.fail = None
                engine.execute(apply=True)
                self.assertIsNone(b.p); self.assertIsNone(b.i); self.assertIsNone(b.t)

    def test_nm_residual_rules_retain_guard(self):
        self.backend.leftover = True
        with self.assertRaises(rb.OperationError): self.engine.execute(apply=True)
        self.assertNotIn("delete_table", self.backend.calls)
        self.assertIsNotNone(self.backend.t)

    def test_success_exit_without_actual_removal_is_not_trusted(self):
        for stage in ["down", "delete_profile", "delete_iface", "delete_table"]:
            with self.subTest(stage=stage):
                b = FakeBackend(self.owner)
                original = b.run
                def sticky(argv):
                    saved = copy.deepcopy((b.p,b.i,b.t,b.a))
                    output = original(argv)
                    if b.calls[-1] == stage:
                        b.p,b.i,b.t,b.a = saved
                    return output
                b.run = sticky
                with self.assertRaises(rb.OperationError):
                    rb.Rollback(self.owner,b,lambda _:None).execute(apply=True)
                self.assertIsNotNone(b.t)

    def test_ownership_collisions_refuse_all_mutations(self):
        collisions = [("p", "name", "Hotspot"), ("p", "interface", rb.STA),
                      ("p", "autoconnect", "yes"), ("p", "mode", "infrastructure"),
                      ("i", "mac", "02:00:00:00:10:01"), ("i", "phy", 1),
                      ("i", "ifindex", 99), ("i", "mode", "monitor"),
                      ("t", "name", "aag_hotspot"), ("t", "comment", "unrelated"),
                      ("t", "handle", 99), ("t", "family", "ip")]
        for obj, key, value in collisions:
            with self.subTest(obj=obj,key=key):
                b = FakeBackend(self.owner); getattr(b, obj)[key] = value
                with self.assertRaises(rb.SafetyError):
                    rb.Rollback(self.owner, b, lambda _: None).execute(apply=True)
                self.assertEqual(b.calls, [])

    def test_unrelated_connection_on_vif_is_protected(self):
        self.backend.a[sorted(rb.PROTECTED_UUIDS)[0]] = [self.owner.vif]
        with self.assertRaises(rb.SafetyError): self.engine.execute(apply=True)
        self.assertEqual(self.backend.calls, [])

    def test_test_uuid_on_real_wifi_refused(self):
        self.backend.a[self.owner.profile_uuid] = [rb.STA]
        with self.assertRaises(rb.SafetyError): self.engine.execute(apply=True)
        self.assertEqual(self.backend.calls, [])

    def test_recheck_catches_identity_change_after_down(self):
        run = self.backend.run
        def changed(argv):
            result = run(argv)
            if self.backend.calls[-1] == "down": self.backend.i["mac"] = "02:00:00:00:11:22"
            return result
        self.backend.run = changed
        with self.assertRaises(rb.SafetyError): self.engine.execute(apply=True)
        self.assertEqual(self.backend.calls, ["down"])
        self.assertIsNotNone(self.backend.t)

    def test_journaled_restoration_is_idempotent(self):
        self.data["changes"] = {"wifi_radio_enabled": True, "sta_autoconnect_disabled": True}
        o = rb.validate_manifest(self.data, BOOT); b = FakeBackend(o)
        engine = rb.Rollback(o, b, lambda _: None)
        engine.execute(apply=True)
        self.assertEqual(b.calls[-2:], ["radio_off", "autoconnect_yes"])
        count = len(b.calls); engine.execute(apply=True)
        self.assertEqual(len(b.calls), count)

    def test_new_wifi_link_defers_global_restoration(self):
        self.data["changes"]["wifi_radio_enabled"] = True
        o = rb.validate_manifest(self.data, BOOT); b = FakeBackend(o); b.idle = False
        with self.assertRaises(rb.OperationError): rb.Rollback(o, b, lambda _: None).execute(apply=True)
        self.assertNotIn("radio_off", b.calls)
        self.assertEqual(b.radio_value, "enabled")
        self.assertIsNone(b.i)

    def test_no_restoration_without_journal(self):
        self.engine.execute(apply=True)
        self.assertEqual(self.backend.radio_value, "enabled")
        self.assertFalse(self.backend.auto_value)

    def test_protected_uuids_cannot_be_authorized(self):
        for uid in rb.PROTECTED_UUIDS:
            self.data["resources"]["profile_uuid"] = uid
            with self.assertRaises(rb.SafetyError): rb.validate_manifest(self.data, BOOT)

    def test_other_baseline_profile_is_protected(self):
        self.data["baseline"]["profile_uuids"].append(self.data["resources"]["profile_uuid"])
        with self.assertRaises(rb.SafetyError): rb.validate_manifest(self.data, BOOT)

    def test_stale_boot_and_unexpected_fields(self):
        with self.assertRaises(rb.SafetyError): rb.validate_manifest(self.data, "different-boot")
        self.data["shell_command"] = "unsafe"
        with self.assertRaises(rb.SafetyError): rb.validate_manifest(self.data, BOOT)

    def test_preexisting_interface_or_mac_collision_refused(self):
        for key, value in [("interface_names", self.owner.vif), ("interface_macs", self.owner.mac)]:
            m = manifest(); m["baseline"][key].append(value)
            with self.assertRaises(rb.SafetyError): rb.validate_manifest(m, BOOT)

    def test_malformed_or_injected_identifiers(self):
        for bad in ["../../wwan0", "uuid; reboot", "$(false)", None, 12]:
            m = manifest(); m["resources"]["profile_uuid"] = bad
            with self.assertRaises(rb.SafetyError): rb.validate_manifest(m, BOOT)

    def test_duplicate_json_keys_refused(self):
        with self.assertRaises(rb.SafetyError):
            json.loads('{"schema":1,"schema":2}', object_pairs_hook=rb.reject_duplicates)

    def test_state_file_trust_checks(self):
        valid = dict(st_uid=0, st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_size=100)
        rb.verify_private(SimpleNamespace(**valid))
        for key, value in [("st_uid",1000),("st_mode",stat.S_IFREG|0o644),
                           ("st_mode",stat.S_IFLNK|0o600),("st_nlink",2),("st_size",65537)]:
            data = dict(valid);data[key]=value
            with self.assertRaises(rb.SafetyError): rb.verify_private(SimpleNamespace(**data))

    def test_busy_lock_prevents_backend_access(self):
        parent = SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o755)
        child = SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o700)
        with patch.object(rb.os,"open",side_effect=[90,91]), \
             patch.object(rb.os,"fstat",side_effect=[parent,child]), patch.object(rb.os,"close"), \
             patch.object(rb.os,"geteuid",return_value=0), \
             patch.object(rb.fcntl,"flock",side_effect=BlockingIOError), \
             patch.object(rb,"Backend",side_effect=AssertionError("network access forbidden")), \
             patch("builtins.print"):
            self.assertEqual(rb.main(["--apply"]),5)

    def test_native_nm_table_also_blocks_guard_cleanup(self):
        b=rb.Backend()
        with patch.object(b,"json_run",return_value={"nftables":[{"table":{"name":"nm-shared-"+self.owner.vif}}]}), \
             patch.object(b,"run",side_effect=AssertionError("unneeded command")):
            self.assertTrue(b.nm_rules_remain(self.owner))

    def test_absent_runtime_state_never_constructs_backend(self):
        rootst = SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR|0o755)
        with patch.object(rb.os,"open",side_effect=[99,FileNotFoundError]), \
             patch.object(rb.os,"fstat",return_value=rootst), patch.object(rb.os,"close"), \
             patch.object(rb,"Backend",side_effect=AssertionError("network access forbidden")), \
             patch("builtins.print"):
            self.assertEqual(rb.main(["--apply"]),0)

    def test_noop_guard_refuses_concurrently_created_state(self):
        parent = SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o755)
        with patch.object(rb.os,"open",side_effect=[90,91]), \
             patch.object(rb.os,"fstat",return_value=parent), patch.object(rb.os,"close"), \
             patch.object(rb,"Backend",side_effect=AssertionError("network access forbidden")), \
             patch("builtins.print"):
            self.assertEqual(rb.main(["--apply","--require-no-test"]),3)

    def test_command_errors_do_not_print_raw_output(self):
        output=SimpleNamespace(returncode=10, stdout="secret-value", stderr="secret-value")
        with patch.object(rb.subprocess,"run",return_value=output):
            with self.assertRaises(rb.OperationError) as caught:
                rb.Backend().run(["/usr/bin/nmcli","connection","show"])
        self.assertNotIn("secret-value",str(caught.exception))

    def test_multiple_active_instances_cannot_hide_real_wifi(self):
        b=rb.Backend();uid=self.owner.profile_uuid
        with patch.object(b,"run",return_value=f"{uid}:{rb.STA}\n{uid}:{self.owner.vif}"):
            with self.assertRaises(rb.SafetyError):b.active()

    def test_radio_idle_checks_cover_nm_and_kernel_links(self):
        for nm_state, kernel_type, link, expected in [
            ("30 (disconnected)","managed","Not connected.",True),
            ("100 (connected)","managed","Not connected.",False),
            ("40 (connecting)","managed","Not connected.",False),
            ("10 (unmanaged)","managed","Connected to 02:00:00:00:11:22",False),
            ("30 (disconnected)","AP","Not connected.",False),
            ("30 (disconnected)","monitor","Not connected.",False),
        ]:
            with self.subTest(nm_state=nm_state,kernel_type=kernel_type,link=link):
                def reply(argv):
                    if argv[-2:]==["device","status"]: return rb.STA+":wifi"
                    if "GENERAL.STATE" in argv:return nm_state
                    if argv==["/usr/sbin/iw","dev"]:return f"phy#0\n\tInterface {rb.STA}\n\t\ttype {kernel_type}"
                    if argv[-1]=="link":return link
                    raise AssertionError(argv)
                b=rb.Backend()
                with patch.object(b,"run",side_effect=reply):self.assertEqual(b.wifi_idle(),expected)


    def test_idle_nm_p2p_control_object_is_not_a_connected_link(self):
        for p2p_state, control_type, control_phy, extra, expected in [
            ("30 (disconnected)", "P2P-device", 0, "", True),
            ("20 (unavailable)", "P2P-device", 0, "", True),
            ("40 (connecting)", "P2P-device", 0, "", False),
            ("100 (connected)", "P2P-device", 0, "", False),
            ("10 (unmanaged)", "P2P-device", 0, "", False),
            ("30 (disconnected)", "AP", 0, "", False),
            ("30 (disconnected)", "P2P-device", 1, "", False),
            ("30 (disconnected)", "P2P-device", 0, "\n\tInterface group0\n\t\ttype P2P-GO", False),
            ("30 (disconnected)", "P2P-device", 0, "\n\tInterface group0\n\t\ttype P2P-client", False),
        ]:
            with self.subTest(p2p_state=p2p_state,control_type=control_type,control_phy=control_phy,extra=extra):
                def reply(argv):
                    if argv[-2:] == ["device", "status"]:
                        return rb.STA + ":wifi\np2p-dev-" + rb.STA + ":wifi-p2p"
                    if "GENERAL.STATE" in argv:
                        return p2p_state if argv[-1].startswith("p2p-dev-") else "30 (disconnected)"
                    if argv == ["/usr/sbin/iw", "dev"]:
                        return (f"phy#{control_phy}\n\tUnnamed/non-netdev interface\n\t\ttype {control_type}\n"
                                f"phy#0\n\tInterface {rb.STA}\n\t\ttype managed" + extra)
                    if argv[-1] == "link": return "Not connected."
                    raise AssertionError(argv)
                b = rb.Backend()
                with patch.object(b, "run", side_effect=reply):
                    self.assertEqual(b.wifi_idle(), expected)

if __name__ == "__main__":
    unittest.main()
