# v0.3.0 acceptance status

Host-side installed live acceptance passed on the documented Ubuntu 26.04 system.
The acceptance runner completed Local-only, dynamic Cellular Internet, OFF cleanup,
and bounded transitions (OFF→Local→OFF, OFF→Internet→OFF, Local→Internet→OFF,
Internet→Local→OFF). Final OFF, baseline restoration, protected-profile preservation,
and unrelated-service preservation were verified.

The live Cellular path was selected from the kernel public route and NetworkManager
metadata using the current 019 eSIM profile with a UUID different from the historic
development UUID. This confirms that no fixed cellular UUID/provider/device binding
is required. Local-only also passed with UPLINK_TYPE=NONE_REQUIRED.

The installed GUI checks passed in OFF, Local, and Internet modes for English and
Hebrew RTL, password reveal/copy/auto-hide, device-page rendering, tray mode, and
language changes without a hotspot restart. No physical client was associated during
this final run, so client continuity/Internet and BeeBEEP remain NOT_TESTED.

Public candidate evidence includes 242 hardware-free tests, 215 bilingual GTK checks,
password GUI checks, static/privacy checks, and 31 isolated packet-policy checks for
dynamic egress, RFC1918 upstreams, Local IPv4/IPv6/DNS isolation, flow downgrade,
and unrelated-interface protection. Staged install/idempotency/uninstall and archive
extraction pass.

Ethernet live validation is NOT_TESTED_NO_ACTIVE_ETHERNET. Same-radio Wi-Fi STA+AP
remains UNVALIDATED_DISABLED; capability and same-channel handling are tested, but
no production Wi-Fi uplink claim is made. Physical-client and BeeBEEP acceptance
remain NOT_TESTED.

---

# Public release validation

The initial public preview is based on the accepted 0.2.0 GTK/NetworkManager
implementation. Private development history, machine reports, installed receipts,
raw network dumps and recovery-runner artifacts are excluded from public history.

The development source baseline passed 276 local tests before publication work.
The public suite contains **184 tests** focused on distributed runtime, readiness,
cleanup, operation locks, client joins/expiry, GUI/tray models, packaging and local
binding. Development-only forensic/live-runner harnesses are not shipped; their
omission is not represented as a pass of those tests in the public artifact.

Public checks performed without activating a real hotspot:

- Python/shell syntax, desktop entry and fixed Polkit scope.
- ShellCheck 0.11.0, official checksum-verified tool.
- 184 mock/unit/regression tests, including Internet/local/OFF transitions,
  readiness timeout/rfkill cases, partial cleanup and ownership refusal.
- Read-only environment selection and unbound/invalid binding refusal.
- Gitleaks 8.30.1 and dedicated privacy/large-file checks.
- Archive extraction, staged installation, idempotent repeat, launcher/CLI/helper
  layout and syntax, and full extracted-tree tests.
- Staged uninstall/dry-run/idempotency, with synthetic unrelated profile and
  credential sentinels preserved.
- Release file inventory and SHA256 checksums; deterministic archive metadata.
- Clean application screenshots with synthetic data; tray menu is a labeled preview.

The archive tests operate inside temporary directories. They never activate an AP,
change firewall state, run the production OFF path, read passwords, reconfigure
modem/GNSS or modify the installed production package.

The GitHub CI workflow repeats syntax, unit/regression, secret/privacy/history,
artifact extraction/staging and reproducibility checks on Ubuntu 24.04 runners.
That runner is a **mock-test environment**, not an additional supported installation
platform. See the repository's Actions tab for the checks attached to the release
commit.

External-client Internet/reachability and BeeBEEP acceptance remain NOT_TESTED.
Wi-Fi STA+AP uplink remains UNVALIDATED_DISABLED. The public binding layer has no
new live hardware acceptance; this is why the first release remains a preview.

## 0.2.2 password reveal

The sanitized source passes 197 hardware-free unit/transaction tests, 33 real-GTK
synthetic reveal/clipboard checks, existing GUI/tray regressions, and 69 layout
checks. Packaging extraction, staged install/uninstall and privacy/secret scans
pass. OFF, Internet and Local fixtures cover masked initial display, reveal, hide,
copy, expiry, cancellation/denial, helper failure and late reply disposal.

The five-file update was installed on the existing development machine, with
source hashes matched and 287 regressions passing against installed modules.
Actual OFF-mode reveal/copy through Polkit passed. Credential permissions remained
root-owned 0600; real-secret checks of status, doctor, captured output, journal and
Git candidates passed. Network baseline was restored to OFF.

Internet live validation was blocked by a pre-existing mismatch between the
currently active cellular profile and that installation's fixed cellular binding.
The binding and networking code were preserved. Internet reveal passes mocks;
it is not counted as live PASS. Independent Local-only live validation did not complete OS authentication; the
pending request was cancelled before activation. Local reveal passes mocks but
is not counted as live PASS. No real associated-client continuity is claimed.
Physical-client/BeeBEEP acceptance and Wi-Fi STA+AP remain unvalidated.

The public checkout also preserved three newer upstream documentation/privacy
commits. The historical scanner's known public project identity is now normalized
only in its exact source-file path (as it already was in commit metadata), fixing
a self-match in upstream history. New tests keep unrelated private emails blocked.
