# Mac hosts address audit — 2026-10-24

All 28 original aliases in `roles/mac_dev/tasks/hosts.yml` were checked.
Twenty-three have current address evidence. Five legacy mappings remain
unverified and unchanged. This audit changed repository files only.
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

## Unverified legacy entries

No replacement address was inferred from a failed connection. These entries
remain in the managed block because a timeout or absent guest does not prove
that a hostname was retired or moved.

| Alias | Unchanged address | Audit result |
| --- | --- | --- |
| `nyx` | `10.10.30.2` | Absent from the current two-node cluster and local Proxmox inventory; TCP 22 and 8006 did not connect |
| `gallery-dl` | `10.10.40.118` | No matching guest in current cluster resources; TCP 22 did not connect |
| `stash` | `10.10.40.228` | No matching guest in current cluster resources; TCP 22 and 9999 did not connect |
| `cobbleverse-nash` | `10.10.40.248` | Ignored Minecraft configuration still lists VMID 114 here, but that guest is absent from live cluster resources; TCP 22 and 25565 did not connect |
| `arachne` | `10.10.70.50` | Outside Proxmox; no current authoritative address source found; TCP 22 and 80 did not connect |

Confirm these hosts against current DHCP reservations, their consoles, or
retirement records before changing or deleting their mappings. An unreachable
port can indicate an offline device or filtering. It does not establish that
an address is stale.

## Scope and maintenance

This is an address audit, not a full application health check. The verified
addresses reflect the observation date. DHCP assignments can change later.
Recheck live guest addresses and application bind addresses before future edits.
Keep raw discovery and credential-bearing inventory files outside Git.
