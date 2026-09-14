# Architecture

`gui.py` renders the Hebrew GTK4/Libadwaita views. `tray.py` exports a user-session
StatusNotifierItem/DBusMenu. Both consume the existing sanitized status transport
in `client.py`; neither owns network state. `cli.py` uses that same transport.

Explicit mode/password requests reach the fixed `/usr/libexec/aag-hotspot-helper`
through Polkit. The policy authorizes only that executable, whose parser accepts
fixed commands. There is no arbitrary shell, interface command or firewall script
argument. GUI and status reads remain unprivileged.

`controller.py` sequences preflight, ownership journal, guard, radio readiness,
NetworkManager transient profile activation and supervisor checks. Operation locks
are bounded kernel flocks; PID files are never cleanup authority. Failure paths
reuse scoped stop/rollback. NetworkManager supplies DHCP/DNS and masquerading;
`policy.py` generates only the AAG table/chain expressions.

The installation binding module supplies validated local interface/radio/profile
identifiers. It replaces development-machine constants; the protocol, guard policy,
readiness sequence and mode restrictions remain the same. An absent/untrusted
binding disables real activation. Root-owned installation receipts reject modified
or unowned files during update/removal.

Runtime state lives under `/run/aag-hotspot`; credentials under
`/var/lib/aag-hotspot`. Persistent credentials are root-only 0600. Current status is
sanitized and contains no password. All pre-existing profile UUIDs are captured in
each operation's private baseline; generated AAG UUIDs must not collide with them.
Removal requires the complete profile/interface/table ownership proof, not a name
prefix. The generic Hotspot profile and locally bound cellular profile remain
protected.

The on-demand systemd supervisor has no boot-install target. Install does not
start or enable it. It operates only for explicitly started AAG sessions.
