# Security model

The protected boundaries are root-owned installed code, the fixed Polkit helper,
validated local binding and private runtime ownership journal. Desktop clients
cannot submit nft expressions, shell commands, uplink names or modem operations.
Normal Linux administrator authentication remains required; no sudoers, PAM or
Polkit bypass is installed.

Password setup uses masked entry/secure terminal input and helper stdin. Passwords
are absent from command arguments, public status, diagnostics, tray and logs.
Neither status nor the GUI offers stored-secret retrieval. Never share credential
files or saved NetworkManager profiles.

AAG's only firewall table is `inet aag_hotspot`, with a per-session ownership marker
and verified table/chain receipts. It does not flush the global ruleset or modify
Docker/Tailscale tables. NetworkManager owns its shared-mode rules. OFF waits for
NM-owned sharing cleanup and removes only proven AAG state.

Local-only mode drops external IPv4 forwarding before any outside-interface accept,
blocks IPv6 ingress/forward/output for the AP and disables AP IPv6 addressing.
Recursive DNS is blocked, including an already-established DNS flow on downgrade.
Internet mode forwards only over `wwan0`, blocks private/link-local/CGNAT/multicast
upstream destinations and admits related replies. This is host-side structural
policy evidence; actual client traffic still requires hardware acceptance.

Host services are intentionally restricted. DHCP, permitted Internet-mode DNS,
ICMP and selected LAN discovery/chat ports are allowed; arbitrary host SSH/proxies
and Docker-published services are not exposed. Same-LAN clients can communicate
subject to their own services/firewalls. This is not client-to-client isolation.

Root users and other privileged network managers can change system policy. AAG
cannot override their drops and must not silently repair their state. Subnet,
route, device identity and ownership conflicts cause refusal or scoped cleanup.
A crash/power loss can leave evidence requiring administrator review; never delete
an unknown object just because its name begins with AAG.

Publication checks use Gitleaks, a privacy scanner, clean staging and public-history
verification. Scanners are defense in depth, not a formal proof that all security
bugs or all possible sensitive strings are absent.
