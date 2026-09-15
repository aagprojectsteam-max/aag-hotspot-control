# Engineering Handoff — AAG Hotspot Control

## Purpose

This document preserves the engineering story, safety model, validation boundary and maintenance procedure for AAG Hotspot Control. It complements the public README and should be updated whenever a new hardware acceptance changes what the project can truthfully claim.

## Goal

Build a native Ubuntu/GNOME controller that can create a Wi-Fi AP in three explicit states: Internet sharing through the supported cellular uplink, local-only LAN without Internet forwarding, and OFF. The GUI must remain unprivileged; privileged networking changes must be narrow, auditable and reversible.

## Development environment and evidence boundary

The host-side implementation was exercised on Ubuntu 26.04 x86_64, GNOME, NetworkManager 1.54, Intel Wi-Fi with AP/virtual-interface support, and an FM350 cellular path using `wwan0mbim0` / `wwan0`. The public release deliberately does not generalize this into a universal Linux/hardware compatibility claim.

## Architecture decisions

The application uses a GTK4/Libadwaita Hebrew RTL GUI plus an independent CLI. Privileged operations pass through a fixed Polkit helper into a bounded controller with ownership tracking. NetworkManager provides AP/DHCP/DNS/NAT behavior; an explicitly scoped `inet aag_hotspot` nftables guard enforces the project's additional local-only policy. The application owns only its generated AAG resources and refuses destructive cleanup of resources it cannot prove it owns.

The GUI is never run as root. There is no broad sudoers rule, global firewall flush, automatic NetworkManager restart, modem reconfiguration, or automatic hotspot activation at installation.

## Modes

**Internet:** create the AAG AP and share the already-active, bound cellular uplink. The program does not establish the cellular connection itself.

**Local only:** associated clients can communicate on the hotspot LAN subject to their own firewalls/services, while external IPv4 forwarding, IPv6 bypass and recursive DNS are blocked by the AAG policy. This does not mean arbitrary services on the laptop are exposed.

**OFF:** use the ownership-checked cleanup path to remove the active AAG-owned session and partial resources.

## Important compatibility gates

Installation/readiness checks include Ubuntu/architecture, NetworkManager, required programs/libraries, existing IPv4 forwarding, a managed Wi-Fi interface with AP capability, and legal 2.4-GHz channel 6. Runtime refuses incompatible or ambiguous conditions such as an active/connecting Wi-Fi station on the intended radio, overlapping `10.77.0.0/24`, occupied AAG resource names, or an unexpected Internet route.

Same-radio Wi-Fi STA + AP uplink remains **UNVALIDATED and DISABLED**. The program never disconnects an existing Wi-Fi station merely to make the hotspot possible.

## Development problems and fixes worth preserving

Hardware testing showed that creating an AP is not equivalent to proving end-to-end client Internet. Device readiness can race NetworkManager, so activation is bounded and must clean up on timeout/failure. Partial operations require an idempotent OFF/recovery path. Existing Docker, Tailscale, NetworkManager profiles and unrelated firewall ownership must be preserved; broad cleanup is forbidden.

The public package therefore records non-secret hardware/profile bindings, uses ownership journals/receipts, refuses unowned/modified installed files, and separates read-only status/doctor operations from privileged state transitions.

## Client reporting

Associated stations come from `iw station dump`; DHCP leases provide IPv4/hostname and a reachable neighbor can be an address fallback. A lease without a currently associated station is not counted as connected. Client snapshots expire rather than presenting stale devices indefinitely. The GUI refreshes in a background worker.

## Credentials

The SSID is `AAG-Hotspot`, host address `10.77.0.1/24`, currently 2.4 GHz channel 6. Passwords are configured through a secure prompt/menu, stored root-owned mode 0600, and never returned by status, doctor, tray or diagnostics. There is intentionally no stored-password reveal API.

## Installation/update/removal

Public release installation is from the verified tarball plus `SHA256SUMS` and `release-manifest.json`. `install.sh --check` is read-only. Normal installation creates no hotspot and no autostart. Updating requires the hotspot to be OFF; unchanged files are skipped while modified/unowned installed files cause refusal. `--rebind` is explicit and reads the intended current environment rather than silently choosing another uplink.

`uninstall.sh` first invokes the installed ownership-checked OFF path and only removes receipt-owned files after cleanup succeeds. It preserves unrelated saved Wi-Fi profiles, the generic NetworkManager Hotspot profile, cellular profiles, Docker and Tailscale. Credentials are retained unless `--purge-credentials` is explicitly requested.

## Testing and validation

The development baseline passed **276 local tests** before public-publication work. The distributed public suite contains **184 mock/unit/regression tests** covering runtime, readiness, cleanup, operation locks, client joins/expiry, GUI/tray models, packaging and binding. Public checks also include syntax, desktop/Polkit scope, ShellCheck, Gitleaks/privacy/large-file checks, archive extraction, staged installation, repeat/idempotency, staged uninstall, unrelated-resource sentinels, release inventory/checksums and deterministic archive metadata.

GitHub Actions repeats hardware-free checks on Ubuntu 24.04 runners. That runner is a CI environment, not evidence that Ubuntu 24.04 is a supported physical installation target.

The public validation intentionally did **not** activate a real hotspot during packaging verification. External-client Internet/reachability, BeeBEEP acceptance, and same-radio STA+AP remain outside the proven public boundary. Screenshots use synthetic data and are not hardware evidence.

## Release state

Current public preview is **v0.2.1**. The release is intentionally labeled preview because the public binding/package path has strong mock/staging evidence but does not add a fresh separate-machine physical-client acceptance.

## Repository map

- `README.md` — complete public usage and limitations.
- `docs/ARCHITECTURE.md` — component and ownership design.
- `docs/COMPATIBILITY.md` — environment gates.
- `docs/HARDWARE-TESTING.md` — hardware procedure/evidence.
- `docs/SECURITY-MODEL.md` — threat/privilege model.
- `docs/TROUBLESHOOTING.md` — failure diagnosis.
- `docs/VALIDATION.md` — public release evidence boundary.
- `docs/CLI.md` — command reference.
- `tests/` — distributed public tests.
- `.github/workflows/ci.yml` — hosted validation.
- `install.sh` / `uninstall.sh` — ownership-aware lifecycle.
- `src/`, `bin/`, `systemd/`, `polkit/` — runtime components.

## Release checklist for maintainers

Before expanding support claims: run all tests and static/privacy checks; stage install/update/uninstall; verify deterministic release files and checksums; inspect privilege boundaries; perform a reviewed live-hardware test for networking changes; test rollback/partial failure; validate at least one external client when claiming client connectivity; update README, CHANGELOG, VALIDATION and this HANDOFF; then publish and independently verify the release assets.

## Historical integrity rule

Do not turn mock/staging success into a hardware claim. Do not turn a screenshot into client acceptance. Preserve failures and unvalidated states explicitly. The words PASS, SUPPORTED and VERIFIED should always name the exact layer they apply to.

## Current handoff status

As of the documentation audit on 2026-09-15, this repository has extensive README, architecture, CLI, compatibility, hardware-testing, security, troubleshooting and validation documentation, release notes/changelog, CI, issue templates, packaging/install/uninstall paths, and this long-form handoff. The main remaining documentation obligation is to append future real-client acceptance evidence when it actually exists.