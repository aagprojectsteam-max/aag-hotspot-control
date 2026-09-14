# Security policy

The latest public 0.2.x preview is the supported security-reporting target.
It is not a claim of a formal audit or compatibility with every firewall/VPN setup.

Use [GitHub private vulnerability reporting](https://github.com/aagprojectsteam-max/aag-hotspot-control/security/advisories/new).
Do not open a public issue with a working exploit, password, token, full network
snapshot or private identifier. If private reporting is unavailable, open a public
issue asking for a private contact channel **without vulnerability details**.

Include the affected release/commit, Ubuntu/NetworkManager versions, a minimal
sanitized reproducer, expected/actual behavior and whether cleanup completed.
Do not attach `/var/lib/aag-hotspot/credentials.json`, saved NetworkManager profiles,
raw firewall rules, terminal history or real client identifiers.

The security boundary is the fixed Polkit helper and ownership-checked backend.
The GUI is never root. The installer does not add sudoers grants or disable
Polkit/PAM. Local-only mode blocks external forwarding, but this is not a sandbox
against a malicious root user or a replacement for each client's firewall.
See [security model](docs/SECURITY-MODEL.md).

Security reports receive best-effort maintainer review; no response-time guarantee
or paid support is implied.
