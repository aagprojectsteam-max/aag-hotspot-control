# Architecture

`gui.py` renders the English/Hebrew GTK4/Libadwaita views. `tray.py` exports a user-session
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
prefix. The generic Hotspot profile and every pre-existing profile remain
protected.

The on-demand systemd supervisor has no boot-install target. Install does not
start or enable it. It operates only for explicitly started AAG sessions.

## Selection and identity

`uplink.Uplink` records kernel output interface, type, NM device, connection display
name/UUID, metric, gateway, source address, route table, support/validation flags and
reason. `ip -j -4 route get` selects two public destinations. Inconsistent selected
paths are refused instead of guessing another default. A fibmatch lookup supplies
diagnostic metric metadata. No first-default/first-connected selection is used.

NetworkManager D-Bus GetDeviceByIpIface and Device.IpInterface correlate a WWAN
control device with its actual kernel IP interface. Device and active-connection
types/states classify Cellular/Ethernet/Wi-Fi. Names and UUIDs are descriptive only.
Any changed UUID/provider with the same suitable route remains eligible. Source,
gateway, device or route-table changes trigger safe shutdown during supervision;
a new Internet invocation selects the current path. Forwarded route lookups from
the AP subnet additionally verify that policy routing agrees with the host path.

Virtual/VPN/bridge/tunnel/AAG interfaces are rejected by validated interface names,
NetworkManager type, and kernel link kind. An unsupported selected path is reported;
there is no silent fallback to another uplink. No connectivity probe or route is
needed to start, maintain or downgrade to Local mode.

## Radio and Wi-Fi coexistence

The protected installation binding schema 2 contains only the AP radio interface
and wiphy. It contains no cellular UUID, protected-profile identity or uplink name.
Every pre-existing profile is protected through the session baseline inventory.

Normal Cellular/Ethernet/Local activation retains the tested idle-radio sequence
and bounded device readiness. Another active AP/STA is preserved and blocks this
path. Experimental coexistence planning reads valid interface-combination limits,
STA wiphy/frequency and regulatory channel flags. It selects the STA channel,
including legal 5 GHz channels, never blindly channel 6. The STA path never toggles
the radio or changes upstream autoconnect. Channel changes fail safely.

Wi-Fi production activation remains UNVALIDATED_DISABLED. The backend's internal
validation seam can exercise an already connected STA; it is not a CLI/helper
argument, preference or broad privilege escape. Advertised capability alone cannot
enable production support. Live STA+AP needs an available, authorized, already
connected upstream and separate evidence. No saved Wi-Fi credential is inspected.

## Firewall and service boundaries

`rules(vif, mode, uplink=None)` strictly validates interface strings. Internet
forwarding is accepted only from the owned AP to the selected interface and for
established/related return traffic. AAG drops all other AP forwarding. The guard
permits RFC1918 destinations on the selected physical uplink, supporting ordinary
private upstream routers, while excluding Docker/Tailscale/ZeroTier interfaces.
Local mode permits same-AP subnet forwarding only and drops external IPv4/IPv6.
AP IPv6 remains disabled. Local recursive DNS requests/responses are blocked.

NetworkManager still owns its shared DHCP/DNS and MASQUERADE chains. AAG owns only
its `inet aag_hotspot` filter table and scoped session resources. No global flush,
Docker/Tailscale/ZeroTier edits, modem/GNSS writes, credential permission changes,
Polkit expansion, GUI root execution or autostart are introduced.

## Presentation and package

Status preserves existing keys and adds UPLINK_TYPE, UPLINK_INTERFACE,
UPLINK_CONNECTION, UPLINK_DEVICE, UPLINK_SUPPORTED, UPLINK_REASON and detailed route
metadata. Local reports NONE_REQUIRED. Doctor independently describes the selected
public path and advertised Wi-Fi constraints. Normal GUI source labels show type
and connection name, never UUIDs. Added text uses existing gettext catalogs.

Upgrade installs new modules, migrates public schema-1 radio bindings to schema 2,
and verifies receipt ownership. Installation never activates a hotspot. Only sanitized source and fixture evidence are published.
