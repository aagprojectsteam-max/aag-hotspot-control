# Manual hardware acceptance

CI and the archive test never activate a radio. Use a spare, compatible Ubuntu
machine for real testing and keep an independent route to its console.

1. Verify compatibility and capture private protected-state baselines locally.
2. Confirm OFF, configure the password securely and verify the scoped OFF path.
3. Arm a bounded independent AAG-only cleanup plan before activation.
4. Explicitly activate Internet mode and verify real AP mode/channel/address,
   DHCP/DNS, NM NAT/forwarding, cellular/default route and protected state.
5. With a real external client, validate association, current DHCP address,
   host/client reachability allowed by policy and public Internet via cellular.
6. Switch to local-only; verify external IPv4 and IPv6 traffic is blocked and
   permitted LAN communication still works. Do not infer packet behavior solely
   from a successful command or a synthetic client fixture.
7. Exercise OFF and bounded transitions in both directions. Finish OFF.
8. Check no orphan interface/profile/dnsmasq/AAG rules remain; compare baselines.
9. Keep BeeBEEP tests separate and mark unperformed tests NOT_TESTED.

Never publish raw baselines, passwords, host bindings, client identifiers, modem
identifiers or private firewall/routing snapshots. A test report should state the
versions/hardware family, verdicts and sanitized limitations only. Same-radio Wi-Fi
STA+AP is a separate research task and remains disabled in this release.
