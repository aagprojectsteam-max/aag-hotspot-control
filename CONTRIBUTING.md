# Contributing

Use issues for reproducible bugs and focused feature requests; use Discussions for
usage questions. Keep reports sanitized. Explain Ubuntu, kernel, NetworkManager,
Wi-Fi chipset/driver, mode, expected result and safe diagnostic output.

The primary GUI is Hebrew RTL. English translations and broader hardware support
are welcome, but must not bypass the current compatibility or privilege gates.

On a development machine with Python 3, PyGObject/GTK4/Libadwaita and desktop-file-utils:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 scripts/check-static.py
/usr/bin/python3 scripts/privacy_scan.py
/usr/bin/python3 scripts/build_release.py
/usr/bin/python3 scripts/test_artifact.py dist/aag-hotspot-control-v0.2.1.tar.gz
git diff --check
```

Install ShellCheck for shell validation. CI uses an Ubuntu runner and mock networks;
it does not require a radio, root network access or a client computer. GUI fixture
checks need an ordinary graphical session: `python3 tests/ui_redesign_review.py`.
They do not activate a real hotspot. Output goes to ignored `build/`.

Changes to cleanup, ownership, readiness, locks, profiles, firewall policy or privilege
boundaries require failure-path regression tests. Do not fix tests by weakening those
invariants. Add tests for reconnects and stale data when changing client visibility.

Never run live activation on a production workstation as part of a routine test.
Use a separate machine and the [manual hardware checklist](docs/HARDWARE-TESTING.md).
Do not commit hardware bindings, credentials, personal email/IP/MAC/hostnames,
private evidence or generated artifacts. UUIDs/MACs in tests must be synthetic.

A pull request should explain the user-visible change, scope, tests and remaining
hardware limitations. Contributions to original project files are under MIT;
retain all applicable third-party notices. Do not bundle dependency source without
its license and provenance.
