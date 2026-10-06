# View or copy the Wi-Fi password

Select **הצג סיסמה** below the network information or in the window menu.
This works while OFF, sharing cellular Internet, or running Local-only mode.
Authorize the fixed helper using the desktop administrator dialog when requested.
The Wi-Fi connection is not restarted. Changing the password remains an OFF-only
operation, available separately in the menu.

The **סיסמת Wi-Fi** dialog starts masked. Select **הצג** to reveal, **הסתר** to
hide, or **העתק** (tooltip: **העתק סיסמה**) to copy to the desktop clipboard.
Visible text hides after 30 seconds. The copied password is cleared after 30
seconds, or when the dialog closes, only if the application still owns that
clipboard content. The dialog expires after 60 seconds regardless of activity.
Closing/hiding the main window also clears the secret view. Reopening requires a
new helper request; Polkit may reuse its existing short administrator authorization.

Credentials remain root-owned mode 0600 at the fixed application path. The GUI
runs as the desktop user. The dedicated helper operation reads this file only;
it does not construct a networking backend, acquire an operation lock, publish
status, or modify a profile. The secret travels over an anonymous subprocess pipe,
never a command-line argument, stderr, status/doctor response, report, or file.
Direct output to a terminal or regular file is refused. Errors discard exception
bodies, including malformed credential contents. No new Polkit or sudo rule is
installed.

GTK uses its password entry buffer; the transport's mutable handoff is overwritten
when consumed or discarded. Closing the dialog empties the GTK buffer. Python and
GTK may create transient internal copies; secure erasure of every process-memory
copy cannot be guaranteed. The application does not request clipboard persistence.
A desktop clipboard manager or another application that reads copied text can
retain its own copy; the application cannot retract copies from other processes.

## Verification

Run `python3 -m unittest discover -s tests` for hardware-free regressions.
Run `/usr/bin/python3 tests/gui_password_reveal.py` in a normal desktop session for
synthetic GTK/clipboard tests. `--installed` checks the installed widgets using
synthetic credentials. These tests never activate a hotspot.

`tests/gui_password_live.py off|internet|local` observes the already selected
installed mode and exercises explicit authorized reveal/copy without changing it.
It emits booleans only and never captures a screenshot. Real-client continuity
requires an actual associated device and must not be inferred from mocked tests.

## Existing-installation update

After reviewing this release, an existing matching installation can use
`sudo /usr/bin/python3 -I scripts/install-password-reveal.py` to update only
`gui.py`, `secret_dialog.py`, `client.py`, `helper.py`, and `__init__.py`, plus its
installation receipt. The updater verifies existing receipt hashes, rolls files
back on partial failure, and checks idempotency. It executes no networking command.
Close and reopen the GUI afterward. Do not copy files manually over a modified
installation or replace local hardware bindings with another machine's files.
