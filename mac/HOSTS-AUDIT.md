# Mac hosts address audit — 2026-10-24

All 28 original aliases in `roles/mac_dev/tasks/hosts.yml` were checked.
Twenty-three have current address evidence. The DHCP/retirement follow-up
removed five obsolete aliases. The user confirmed that Gallery and Cobbleverse
are no longer live on 2026-10-24, resolving the final two uncertain entries.
The managed block now has 24 aliases, including the added Seerr name.
This audit changed repository files only.
No live host, application, DNS record, or local `/etc/hosts` file was modified.

## Corrections

| Alias | Previous address | Correct address | Evidence |
| --- | --- | --- | --- |
| `git-mirror-nash` | `10.10.40.119` | `10.10.40.183` | Live IPv4 address inside running Proxmox LXC 119 |
| `deluge-nash` | `10.10.40.217` | `10.10.20.3` | TrueNAS reports Deluge running; configured bind address and an HTTP 200 Deluge response at port 8112 agree |

LXC 117 now identifies itself as `seerr-nash`. The address remains
`10.10.40.172`. The managed block now includes the current name and preserves
`overseerr-nash` as a compatibility alias. The web UI responded as Seerr on
port 5055.

Erebus retains `10.10.10.7`, the management address corrected previously.
Deluge binds to the separate TrueNAS app address `10.10.20.3`. Do not replace
that app address with the management address. `deluge-nash` is now a service
alias for TrueNAS, not the identity of its former LXC or an SSH login target.

## Verified entries

Guest addresses below came from read-only `ip -j -4 addr show scope global`
commands inside the running LXCs. Proxmox IP tags were not treated as proof.

| Managed alias | Address | Current evidence |
| --- | --- | --- |
| `prometheus` | `10.10.30.3` | Connected Proxmox node; current cluster and local inventory agree |
| `atlas` | `10.10.30.9` | Connected Proxmox node; current cluster and local inventory agree |
| `mnemosyne` | `10.10.20.2` | SSH `hostname` returned `mnemosyne`; local inventory agrees |
| `erebus` | `10.10.10.7` | TrueNAS middleware query over SSH; local inventory agrees |
| `pocketid-nash` | `10.10.40.236` | Live LXC 100 address |
| `npm-nash` | `10.10.40.86` | Live LXC 101 address |
| `pxe-nash` | `10.10.40.170` | Live LXC 107 address |
| `prowlarr-nash` | `10.10.40.87` | Live LXC 104 address |
| `sonarr-nash` | `10.10.40.52` | Live LXC 110 address |
| `radarr-nash` | `10.10.40.131` | Live LXC 111 address |
| `deluge-nash` | `10.10.20.3` | Running TrueNAS app and verified Deluge web endpoint |
| `sabnzbd-nash` | `10.10.40.243` | Live LXC 109 address; distinct from the separate TrueNAS SABnzbd app |
| `seerr-nash`, `overseerr-nash` | `10.10.40.172` | Live LXC 117 address and Seerr web endpoint |
| `openwebui-nash` | `10.10.40.177` | Live LXC 118 address |
| `searxng-nash` | `10.10.40.117` | Live LXC 112 address |
| `git-mirror-nash` | `10.10.40.183` | Live LXC 119 address |
| `forgejo-nash` | `10.10.40.38` | Live LXC 103 address |
| `atm10-nash` | `10.10.40.185` | Live LXC 113 address |
| `homestead-nash` | `10.10.40.186` | Live LXC 115 address |
| `yabu-nash` | `10.10.40.202` | Live LXC 116 address |
| `homebridge-nash` | `10.10.40.237` | Live LXC 105 address |
| `spoolman-nash` | `10.10.40.223` | Live LXC 102 address |
| `apt-nash` | `10.10.40.175` | Live LXC 106 address |

## DHCP and retirement follow-up — 2026-10-24

The Arista switch is the DHCP server for VLAN 40. Read-only discovery used
`show dhcp server leases` and the privileged command
`show running-config section dhcp`. The configured DHCP scope is
`10.10.40.0/24`; its dynamic range is `10.10.40.6` through `10.10.40.254`.
The old Gallery, Stash, and Cobbleverse addresses have neither reservations
nor current leases. The switch's DHCP configuration has no VLAN 30 or VLAN 70
scope, so it cannot establish reservations for Nyx or Arachne.

A fresh PVE resource query lists only Atlas and Prometheus as cluster nodes.
None of the five legacy names appears as a current guest. This corroborates
retirement records but does not, by itself, prove retirement.

The UniFi gateway at `192.168.1.1` refused SSH. Its unauthenticated API routes
returned HTTP 401. Gateway DHCP reservations were therefore not available.
No gateway or switch settings were changed. Raw discovery and local inventories
were not committed.

### Removed obsolete aliases

| Removed alias | Previous address | Retirement evidence |
| --- | --- | --- |
| `nyx` | `10.10.30.2` | Commit `f0a1297` intentionally removed Nyx from cluster desired state and reassigned its fallback roles. The current inventory and live cluster contain only Atlas and Prometheus. This removes the obsolete cluster alias; it does not claim that the physical server was destroyed. |
| `stash` | `10.10.40.228` | Commit `36049dd` removed the Stash role and playbook entry. The root `TODO.md` security record explicitly describes the deployment as retired. Current PVE resources and Arista DHCP have no matching guest or address allocation. |
| `arachne` | `10.10.70.50` | Commit `62fbdf3` replaced the OctoPi project with Kuma. Historical local Kuma inventory associates its `tx` host with this address. The `kuma/README.md` retirement record states that the user confirmed its retirement on 2026-10-02 and that inventory entries are stale. The old OctoPi alias was removed; no new use of the physical device was inferred. |
| `gallery-dl` | `10.10.40.118` | The user confirmed on 2026-10-24 that the deployment is no longer live. Earlier checks found no current PVE guest, Arista reservation, or lease. |
| `cobbleverse-nash` | `10.10.40.248` | The user confirmed on 2026-10-24 that the deployment is no longer live. Earlier checks found no live VMID 114, Arista reservation, or lease. |

These removals affect only the Ansible-managed Mac hosts block. No live guest,
physical server, reservation, DNS record, backup, or unmanaged hosts entry was
deleted.

### Resolution of the final two entries

Gallery and Cobbleverse were initially retained because missing guests, leases,
and reservations alone did not prove retirement. The user's 2026-10-24
confirmation supplies the missing evidence. Both aliases are now removed.
Local desired-state declarations were not used as proof that the deployments
remain active. No unresolved legacy aliases remain from this audit.

## Scope and maintenance

This is an address audit, not a full application health check. The verified
addresses reflect the observation date. DHCP assignments can change later.
Recheck live guest addresses and application bind addresses before future edits.
Keep raw discovery and credential-bearing inventory files outside Git.
