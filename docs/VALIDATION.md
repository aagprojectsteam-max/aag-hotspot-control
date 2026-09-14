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
