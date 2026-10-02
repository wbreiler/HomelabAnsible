# Documentation and live-state audit — 2026-10-02

This audit reviewed all 29 tracked Markdown files present at its start, plus
the two local, ignored handoff files. This report is the 30th tracked Markdown
file. Checks were read-only on the infrastructure. Documentation corrections
did not change packages, configuration, services, storage, or reboot any host.

## Follow-up: SSH access and retired Kuma

Later on 2026-10-02, the user confirmed Kuma is retired. Its stale inventory
entry is not an active outage. The user also added the cluster public key to
Arista's `admin` account. Key login now succeeds; the Mac's host-specific SSH
profile was changed from password-only to key-first with password fallback.
This follow-up did not modify switch configuration or reboot any host.

Live Arista checks confirm EOS 4.28.12M, hostname `arista-nash`, the documented
VLAN interfaces/routes, a connected 10G Et1 uplink, and disconnected Nyx Et4.
Full running/startup configuration drift and Ansible authentication remain
unverified.

## Coverage

| Project | Documents reviewed | Validation |
|---|---|---|
| Root | `README.md`, `AGENTS.md`, `TODO.md` | Project entry points, current topology, SSH selectors, and historical security-report wording |
| Proxmox | `README.md`, `AGENTS.md`, `GEMINI.md`, `TODO.md`, `tests/README.md`, `docs/arr-storage.md` | Cluster API, HA, storage, installed versions, selected service APIs, role defaults and playbook wiring |
| PBS | `README.md` | Live product/kernel, services, datastore/pools, sync-job presence, and implementation review |
| Minecraft | `README.md`, `AGENTS.md` | Five live guests, pack/version markers, timer states, updater implementation, public DNS SRV records, and SSH selector |
| TrueNAS | `AGENTS.md`, `README.md`, `REVIEW.md`; `files/{cobalt,fastchannels,lancache,lidarr,spotdl,tdarr,threadfin}/SETUP.md` | Middleware inventory, pool health, app state, seven HTTP endpoints, and implementation review |
| Kuma | `README.md` | Inventory and implementation checked; user later confirmed deployment retired |
| Arista | `README.md` | Implementation checked; key login and read-only device checks subsequently passed |
| Desktop | `README.md`, `ISO_GAP_REPORT.md`, `roles/gaming_pc/README.md` | Implementation checked; fresh WinRM connection timed out |
| Mac | `README.md`, `AGENTS.md` | Local OS/toolchain, four managed user files, SSH configuration and agent socket |
| Local handoffs | `proxmox/HANDOFF.md`, `kuma/HANDOFF.md` | Both read; Proxmox handoff corrected locally, Kuma design history preserved. Both remain ignored. |

## Verified operational snapshot

These facts are observations on the audit date, not permanent placement or
proof that every desired-state file matches its host.

| System | Verified state |
|---|---|
| PVE | Two members: Prometheus and Atlas; both report PVE 9.2.21 and running kernel 7.0.14-19-pve. Quorum is healthy. |
| Placement | All 29 LXCs run on Prometheus. Atlas remains in HA maintenance mode. Hytale VM 122 remains stopped on Atlas. |
| Storage | Prometheus pools report healthy; `helios`, `local-zfs`, `tartarus`, `local`, and PBS storage `mnemosyne` are available. |
| PBS | Mnemosyne runs PBS 4.2.7-1 on Debian 13. Datastore `mneme` uses `/mneme`; the PVE storage ID is `mnemosyne` and namespace is `cluster-nash`. Both PBS services are active. |
| PBS kernel | Running 7.0.14-15-pve; 7.0.14-20-pve is installed but not running. No reboot was performed. |
| TrueNAS | Erebus runs 25.10.4. Data pool `gaia` is ONLINE. Middleware lists 28 datasets, three SMB shares, seven NFS exports, four interfaces, and nine running apps. |
| Router | LXC 123 has 512 MiB RAM and Tailscale 1.102.4. |
| Arr storage | Sonarr 110 and Radarr 111 have no failed units. Their earlier authorized reboot tests passed all five/six configured NFS mounts, ordering, HTTP, and media-user read/write checks. This audit did not repeat those reboots. |
| Minecraft | ATM10 8.2 on 113/124; Better MC v61 on 120; YABU 2.14.0 / Minecraft 26.3 on 116. All five game guests run on Prometheus. |
| Mac | macOS 27.0.1, arm64, Homebrew 7.0.7; four managed user files match. SSH uses the configured Bitwarden agent. |

Live app probes confirmed Sonarr 4.0.20.3014, Radarr 6.4.4.10685, Spoolman
0.27.0, Seerr 3.5.0, Grafana 13.2.3 with database health OK, NexDeck 0.29.1,
Forgejo 16.0.5, Homebridge package 2.0.19, Vaultwarden 1.37.3, and Gitea Mirror
package 3.40.3.
Bambuddy's deployment marker is 1.2.5.7 and its UI returns HTTP 200. Pocket ID's
installed binary checksum matches the pinned 2.17.0 artifact. The README's
other release values were reconciled with tracked role defaults, not assumed
to be live merely because a role declares them.

## Corrections and material findings

1. Corrected obsolete app versions, the three-node cluster description,
   router RAM, PBS identifiers, stale SSH-agent/key instructions, and claims
   that all applications have dedicated managed roles. Added the arr storage
   procedure to the main Proxmox documentation and corrected backup-calendar
   interpretation and gated restore examples.
2. Minecraft documentation now describes actual updater ordering and limits.
   The manual script leaves the service stopped and has no automatic rollback,
   player check, or announcement. Automatic rollback covers the mod directory,
   not every loader/configuration change. Dry-run can still send a notification.
3. TrueNAS documentation no longer presents old object counts or Ollama as
   current. Tdarr's live image reference is untagged while tracked Compose pins
   2.86.01; its exact running binary version was not verified. Reapplying that
   Compose file requires review.
4. The standalone PBS project has no local inventory, and its Tailscale role
   still specifies Bookworm repositories although the live host runs Trixie.
   The documentation now distinguishes compatibility limits from live state.
5. Kuma documentation now distinguishes OS updates from Docker image updates.
   Its optional quorum relay has a single primary, no primary election, and
   a host listener on all IPv4 interfaces. The template's container-loopback
   endpoint cannot reach that host relay. These are code findings, not proof
   that the optional relay is deployed.

## Blocked or unverified checks

| Item | Limit |
|---|---|
| Arista | Initial authentication failure resolved by the user-installed key and client profile correction. EOS, links, VLAN interfaces, and routes verified; full running/startup drift remains unverified. |
| Windows | Fresh WinRM timed out at the configured address/port. Earlier maintenance reached it but failed authentication. Current installed software/hardware and SMB mapping remain unverified. |
| Kuma | Retired, as confirmed by the user. The previous unreachable-host result came from stale inventory. |
| Minecraft external access | All six documented SRV records matched. Router forwards and end-to-end player connections were not tested. Cobbleverse still has DNS but no matching live cluster guest. |
| TrueNAS applications | HTTP/app-state checks do not prove feed/tuner settings, provider downloads, LANCache prefill, GPU encoding, HDR, or client playback. Historical functional tests were not repeated. |

Examples, historical audit conclusions, third-party links, and destructive
procedures were not executed as tests. This was not a new security assessment,
full desired-state convergence run, backup-restore test, or exhaustive UI test.
Historical documents are labeled to avoid presenting old observations as
current proof.

## Validation

Reviewed the combined documentation changes and checked local Markdown link
targets and whitespace. Read-only probes and repository inspection support
the corrections above. TrueNAS lint and syntax checks passed. No deployment
playbook was applied during this documentation audit. Physical host reboots
remain subject to the user's separate all clear.
