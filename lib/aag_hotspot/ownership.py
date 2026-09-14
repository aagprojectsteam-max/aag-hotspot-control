#!/usr/bin/python3
"""Ownership-checked rollback for a future, explicitly authorized AAG AP test.

No creation/activation commands exist here. No manifest means no network actions.
Runtime state is fixed at /run/aag-hotspot-test/manifest.json; there is deliberately
no CLI/environment override, shell execution, or prefix-based resource discovery.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass

STATE_NAME = "aag-hotspot-test"
from .binding import STA, PHY, PROTECTED_UUIDS
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
       "NM_CLI_COLOR": "never"}


class SafetyError(Exception):
    """Unproven ownership or changed identity; make no unsafe change."""


class OperationError(Exception):
    """Required inspection or an owned cleanup action failed."""


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise SafetyError("Manifest schema/keys are invalid.")


def canonical_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def mac_valid(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", value)


@dataclass(frozen=True)
class Ownership:
    test_id: str
    profile_uuid: str
    vif: str
    mac: str
    table: str
    marker: str
    ifindex: object
    table_handle: object
    baseline_radio: str
    baseline_autoconnect: bool
    restore_radio: bool
    restore_autoconnect: bool

    @property
    def profile_name(self):
        return "AAG Hotspot Test " + self.test_id


def validate_manifest(data, boot_id):
    exact_keys(data, ("schema", "test_id", "boot_id", "baseline", "resources", "changes"))
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise SafetyError("Unsupported manifest schema.")
    if not canonical_uuid(data["test_id"]) or uuid.UUID(data["test_id"]).version != 4:
        raise SafetyError("Test ID must be a canonical random UUIDv4.")
    if data["boot_id"] != boot_id:
        raise SafetyError("Manifest belongs to a different boot; refusing stale cleanup.")
    base, res, changes = data["baseline"], data["resources"], data["changes"]
    exact_keys(base, ("profile_uuids", "interface_names", "interface_macs", "wifi_radio", "sta_autoconnect"))
    exact_keys(res, ("profile_uuid", "vif_ifindex", "nft_handle"))
    exact_keys(changes, ("wifi_radio_enabled", "sta_autoconnect_disabled"))
    for key in ("profile_uuids", "interface_names", "interface_macs"):
        values = base[key]
        if not isinstance(values, list) or len(values) > 2048 or not all(isinstance(v, str) for v in values):
            raise SafetyError("Invalid baseline inventory.")
        if len(values) != len(set(values)):
            raise SafetyError("Duplicate baseline identities.")
    if not all(canonical_uuid(v) for v in base["profile_uuids"]):
        raise SafetyError("Invalid baseline profile UUID.")
    if not PROTECTED_UUIDS.issubset(base["profile_uuids"]):
        raise SafetyError("Baseline must include all locally bound protected profiles.")
    if STA not in base["interface_names"] or not all(mac_valid(v) for v in base["interface_macs"]):
        raise SafetyError("Invalid Wi-Fi baseline.")
    if base["wifi_radio"] not in ("enabled", "disabled") or type(base["sta_autoconnect"]) is not bool:
        raise SafetyError("Invalid baseline restoration values.")
    if not all(type(v) is bool for v in changes.values()):
        raise SafetyError("Change journal flags must be booleans.")
    if changes["wifi_radio_enabled"] and base["wifi_radio"] != "disabled":
        raise SafetyError("Only a journaled disabled-to-enabled radio change is restorable.")
    if changes["sta_autoconnect_disabled"] and not base["sta_autoconnect"]:
        raise SafetyError("Only a journaled yes-to-no autoconnect change is restorable.")
    profile_uuid = res["profile_uuid"]
    if (not canonical_uuid(profile_uuid) or uuid.UUID(profile_uuid).version != 4
            or profile_uuid in base["profile_uuids"] or profile_uuid in PROTECTED_UUIDS):
        raise SafetyError("Profile UUID is invalid or belongs to pre-existing state.")
    for key in ("vif_ifindex", "nft_handle"):
        if res[key] is not None and (type(res[key]) is not int or res[key] <= 0):
            raise SafetyError("Invalid creation receipt.")
    token = uuid.UUID(data["test_id"]).hex
    vif = "aaght" + token[:8]
    mac = "02:" + ":".join(token[i:i+2] for i in range(22, 32, 2))
    if vif in base["interface_names"] or mac in base["interface_macs"]:
        raise SafetyError("Planned interface identity was already present before testing.")
    return Ownership(data["test_id"], profile_uuid, vif, mac,
                     "aag_hstest_" + token[:12], "AAG-Hotspot-Control test=" + data["test_id"],
                     res["vif_ifindex"], res["nft_handle"], base["wifi_radio"],
                     base["sta_autoconnect"], changes["wifi_radio_enabled"],
                     changes["sta_autoconnect_disabled"])


class Backend:
    """All process calls have fixed binaries and argument arrays; no shell."""
    def run(self, argv):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, check=False,
                               timeout=25, env=ENV)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OperationError("Required command unavailable or timed out: " + argv[0]) from exc
        if r.returncode:
            # Never print subprocess output: future NM errors may contain secrets.
            raise OperationError(f"{Path(argv[0]).name} command failed (exit {r.returncode}); inspect locally.")
        return r.stdout.strip()

    def json_run(self, argv):
        try:
            return json.loads(self.run(argv))
        except (ValueError, TypeError) as exc:
            raise OperationError("Unexpected JSON from network inspection.") from exc

    def profiles(self):
        return set(self.run(["/usr/bin/nmcli", "-g", "UUID", "connection", "show"]).splitlines())

    def profile(self, owner):
        if owner.profile_uuid not in self.profiles():
            return None
        fields = "connection.uuid,connection.id,connection.type,connection.interface-name,connection.autoconnect,802-11-wireless.mode"
        lines = self.run(["/usr/bin/nmcli", "-g", fields, "connection", "show", "uuid", owner.profile_uuid]).splitlines()
        if len(lines) != 6:
            raise OperationError("Unexpected profile inspection format.")
        return dict(zip(("uuid", "name", "type", "interface", "autoconnect", "mode"), lines))

    def active(self):
        out = self.run(["/usr/bin/nmcli", "-t", "-f", "UUID,DEVICE", "connection", "show", "--active"])
        result = {}
        for line in out.splitlines():
            uid, sep, devices = line.partition(":")
            if not sep or not canonical_uuid(uid):
                raise OperationError("Unexpected active connection inventory.")
            if uid in result:
                raise SafetyError("Multiple active instances of a profile require manual review.")
            result[uid] = devices.split(",") if devices and devices != "--" else []
        return result

    def links(self):
        result = self.json_run(["/usr/sbin/ip", "-j", "link", "show"])
        if not isinstance(result, list):
            raise OperationError("Unexpected interface inventory.")
        return result

    def interface(self, owner):
        links = [x for x in self.links() if x.get("ifname") == owner.vif]
        if not links:
            return None
        if len(links) != 1:
            raise SafetyError("Ambiguous test interface.")
        link = links[0]
        info = self.run(["/usr/sbin/iw", "dev", owner.vif, "info"])
        wiphy = re.search(r"^\s*wiphy (\d+)\s*$", info, re.M)
        mode = re.search(r"^\s*type (\S+)\s*$", info, re.M)
        return {"name": link["ifname"], "mac": link.get("address", "").lower(),
                "ifindex": link.get("ifindex"), "phy": int(wiphy[1]) if wiphy else None,
                "mode": mode[1] if mode else None}

    def table(self, owner):
        entries = self.json_run(["/usr/sbin/nft", "-j", "list", "tables"])
        if not isinstance(entries, dict) or not isinstance(entries.get("nftables"), list):
            raise OperationError("Unexpected nft table inventory.")
        matches = [e["table"] for e in entries["nftables"] if "table" in e
                   and e["table"].get("family") == "inet" and e["table"].get("name") == owner.table]
        if not matches:
            return None
        data = self.json_run(["/usr/sbin/nft", "-a", "-j", "list", "table", "inet", owner.table])
        tables = [e["table"] for e in data.get("nftables", []) if "table" in e]
        if len(tables) != 1:
            raise OperationError("Unexpected owned-table inspection.")
        return tables[0]

    def nm_rules_remain(self, owner):
        markers = ("nm-sh-in-" + owner.vif, "nm-sh-fw-" + owner.vif, "nm-shared-" + owner.vif)
        data = self.json_run(["/usr/sbin/nft", "-j", "list", "tables"])
        if not isinstance(data, dict) or not isinstance(data.get("nftables"), list):
            raise OperationError("Unexpected nft table inventory during NM cleanup verification.")
        if any(e.get("table", {}).get("name") == markers[2] for e in data["nftables"]):
            return True
        for command in ("/usr/sbin/iptables-save", "/usr/sbin/ip6tables-save"):
            text = self.run([command])
            if any(re.search(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])", text) for m in markers):
                return True
        return False

    def radio(self):
        value = self.run(["/usr/bin/nmcli", "-t", "-f", "WIFI", "general", "status"])
        if value not in ("enabled", "disabled"):
            raise OperationError("Unknown Wi-Fi radio state.")
        return value

    def autoconnect(self):
        value = self.run(["/usr/bin/nmcli", "-g", "GENERAL.AUTOCONNECT", "device", "show", STA])
        if value not in ("yes", "no"):
            raise OperationError("Unknown STA device autoconnect state.")
        return value == "yes"

    def wifi_idle(self):
        # Protect all Wi-Fi adapters, including connections in progress and NM-unmanaged STA links.
        devices = self.run(["/usr/bin/nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"])
        idle_p2p = set()
        for line in devices.splitlines():
            name, sep, kind = line.partition(":")
            if not sep:
                raise OperationError("Unknown Wi-Fi device inventory.")
            if kind in ("wifi", "wifi-p2p"):
                state = self.run(["/usr/bin/nmcli", "-g", "GENERAL.STATE", "device", "show", name])
                match = re.match(r"(\d+)\b", state)
                allowed = (20, 30) if kind == "wifi-p2p" else (10, 20, 30, 120)
                if not match or int(match[1]) not in allowed:
                    return False
                if kind == "wifi-p2p":
                    idle_p2p.add(name)
        info = self.run(["/usr/sbin/iw", "dev"])
        phy, current, blocks = None, None, []
        for line in info.splitlines():
            match = re.match(r"phy#(\d+)$", line)
            if match:
                phy, current = int(match[1]), None
            match = re.match(r"\s*Interface (\S+)$", line)
            if match:
                current = {"phy": phy, "name": match[1], "mode": None}
                blocks.append(current)
            elif line.strip() == "Unnamed/non-netdev interface":
                current = {"phy": phy, "name": None, "mode": None}
                blocks.append(current)
            match = re.match(r"\s*type (\S+)$", line)
            if match:
                if current is None or current["mode"] is not None:
                    return False
                current["mode"] = match[1]
        for item in blocks:
            if item["name"] is None:
                # An idle NM discovery/control object is not a P2P data link.
                # Require its idle NM counterpart on this same phy.
                siblings = [x for x in blocks if x["phy"] == item["phy"] and x["name"]
                            and x["mode"] == "managed" and "p2p-dev-" + x["name"] in idle_p2p]
                unnamed = [x for x in blocks if x["phy"] == item["phy"] and x["name"] is None]
                if item["phy"] is None or item["mode"] != "P2P-device" or len(unnamed) != 1 or len(siblings) != 1:
                    return False
            elif item["mode"] != "managed" or self.run(
                    ["/usr/sbin/iw", "dev", item["name"], "link"]) != "Not connected.":
                return False
        return True


class Rollback:
    def __init__(self, owner, backend, emit=print):
        self.o, self.b, self.emit = owner, backend, emit

    def inspect(self):
        o = self.o
        profile, interface, table, active = self.b.profile(o), self.b.interface(o), self.b.table(o), self.b.active()
        if profile is not None and profile != {"uuid": o.profile_uuid, "name": o.profile_name,
                "type": "802-11-wireless", "interface": o.vif, "autoconnect": "no", "mode": "ap"}:
            raise SafetyError("Profile identity/settings no longer match the test manifest.")
        if any(o.vif in devs and uid != o.profile_uuid for uid, devs in active.items()):
            raise SafetyError("The test interface is used by an unrelated active connection.")
        if o.profile_uuid in active and (profile is None or active[o.profile_uuid] != [o.vif]):
            raise SafetyError("Test profile is active on an unexpected device.")
        if interface is not None:
            if (interface["name"] != o.vif or interface["mac"] != o.mac or interface["phy"] != PHY
                    or interface["mode"] not in ("AP", "managed")
                    or (o.ifindex is not None and interface["ifindex"] != o.ifindex)):
                raise SafetyError("Interface name/MAC/phy/receipt does not prove test ownership.")
        if table is not None and (table.get("family") != "inet" or table.get("name") != o.table
                or table.get("comment") != o.marker
                or (o.table_handle is not None and table.get("handle") != o.table_handle)):
            raise SafetyError("Firewall table ownership marker/receipt does not match.")
        return profile, interface, table, active

    def execute(self, apply=False):
        o = self.o
        profile, interface, table, active = self.inspect()
        self.emit("Verified test ownership: " + o.test_id)
        if not apply:
            if o.profile_uuid in active: self.emit("DRY-RUN: would deactivate UUID " + o.profile_uuid)
            if profile: self.emit("DRY-RUN: would delete only test profile UUID " + o.profile_uuid)
            if interface: self.emit("DRY-RUN: would delete owned Wi-Fi interface " + o.vif)
            if table: self.emit("DRY-RUN: would remove inet " + o.table + " only after AP and NM sharing cleanup")
            if o.restore_radio: self.emit("DRY-RUN: radio restoration conditional on no active/connecting Wi-Fi")
            if o.restore_autoconnect: self.emit("DRY-RUN: restore only journaled STA device autoconnect change")
            self.emit("DRY-RUN: no network or state-file writes.")
            return
        if o.profile_uuid in active:
            self.emit("Deactivate owned profile UUID " + o.profile_uuid)
            self.b.run(["/usr/bin/nmcli", "--wait", "15", "connection", "down", "uuid", o.profile_uuid])
        profile, interface, table, active = self.inspect()
        if o.profile_uuid in active:
            raise OperationError("AP deactivation not confirmed; retain the blocking table.")
        if profile:
            self.emit("Delete owned profile UUID " + o.profile_uuid)
            self.b.run(["/usr/bin/nmcli", "--wait", "15", "connection", "delete", "uuid", o.profile_uuid])
        profile, interface, table, active = self.inspect()
        if profile is not None:
            raise OperationError("Profile removal not confirmed; retain the blocking table.")
        if interface:
            self.emit("Delete owned Wi-Fi interface " + o.vif)
            self.b.run(["/usr/sbin/iw", "dev", o.vif, "del"])
        profile, interface, table, active = self.inspect()
        if profile or interface or o.profile_uuid in active:
            raise OperationError("AP absence not confirmed; retain the blocking table.")
        if self.b.nm_rules_remain(o):
            raise OperationError("NM test sharing rules remain; retain the blocking table for manual review.")
        if table:
            self.emit("Delete owned firewall table inet " + o.table)
            self.b.run(["/usr/sbin/nft", "delete", "table", "inet", o.table])
            if self.b.table(o) is not None:
                raise OperationError("Owned firewall table removal not confirmed.")
        # Restorations are compare-before-write, journal-gated, and never activate a profile.
        if o.restore_radio and self.b.radio() != o.baseline_radio:
            if not self.b.wifi_idle():
                raise OperationError("Preserved newly active/connecting Wi-Fi; radio restoration deferred.")
            self.emit("Restore journaled Wi-Fi radio state to disabled (no Wi-Fi links active).")
            self.b.run(["/usr/bin/nmcli", "radio", "wifi", "off"])
            if self.b.radio() != "disabled":
                raise OperationError("Radio restoration not confirmed.")
        if o.restore_autoconnect and self.b.autoconnect() != o.baseline_autoconnect:
            self.emit("Restore journaled STA device autoconnect to yes.")
            self.b.run(["/usr/bin/nmcli", "device", "set", STA, "autoconnect", "yes"])
            if not self.b.autoconnect():
                raise OperationError("Autoconnect restoration not confirmed.")
        self.emit("ROLLBACK_COMPLETE: owned resources absent; no unrelated resources removed.")


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SafetyError("Duplicate JSON manifest key.")
        result[key] = value
    return result


def verify_private(st, directory=False):
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    expected_mode = 0o700 if directory else 0o600
    if st.st_uid != 0 or not expected_type(st.st_mode) or stat.S_IMODE(st.st_mode) != expected_mode:
        raise SafetyError("State must be root-owned with directory 0700 / file 0600 permissions.")
    if not directory and (st.st_nlink != 1 or st.st_size > 65536):
        raise SafetyError("Unsafe manifest link count/size.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", "--inspect", action="store_true", help="inspect only (default)")
    group.add_argument("--apply", action="store_true", help="remove only manifest-proven test resources")
    parser.add_argument("--require-no-test", action="store_true",
                        help="refuse if runtime state exists; enforce safe no-op validation")
    args = parser.parse_args(argv)
    dirfd = None
    try:
        runfd = os.open("/run", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            rootst = os.fstat(runfd)
            if rootst.st_uid != 0 or stat.S_IMODE(rootst.st_mode) & 0o022:
                raise SafetyError("Untrusted /run parent directory.")
            try:
                dirfd = os.open(STATE_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=runfd)
            except FileNotFoundError:
                print("NO_REGISTERED_TEST: /run/aag-hotspot-test is absent; no network commands or writes.")
                return 0
        finally:
            os.close(runfd)
        if args.require_no_test:
            raise SafetyError("No-op validation refuses an existing runtime state directory.")
        verify_private(os.fstat(dirfd), directory=True)
        if os.geteuid() != 0:
            raise SafetyError("Registered-test inspection/cleanup requires administrator execution.")
        try:
            fcntl.flock(dirfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ROLLBACK_BUSY: another test operation holds the ownership lock.", file=sys.stderr)
            return 5
        fd = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            verify_private(os.fstat(stream.fileno()))
            data = json.loads(stream.read(65537), object_pairs_hook=reject_duplicates)
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        owner = validate_manifest(data, boot_id)
        Rollback(owner, Backend()).execute(apply=args.apply)
        # Keep the immutable manifest for repeatability and audit. Never recursively delete /run.
        return 0
    except SafetyError as exc:
        print("ROLLBACK_REFUSED: " + str(exc), file=sys.stderr)
        return 3
    except OperationError as exc:
        print("ROLLBACK_INCOMPLETE: " + str(exc), file=sys.stderr)
        return 4
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ROLLBACK_REFUSED: cannot safely read/interpret state (" + type(exc).__name__ + ").", file=sys.stderr)
        return 3
    finally:
        if dirfd is not None:
            os.close(dirfd)


if __name__ == "__main__":
    sys.exit(main())
