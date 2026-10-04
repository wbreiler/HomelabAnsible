# Homelab hardening task list

Status: inventory complete. Atlas reboot and Minecraft container migrations completed on October 4, 2026.
All five Minecraft servers passed service startup and LAN game status checks. H1/P0 is in progress. Other hardening tasks have not started.

Inventory date: October 4, 2026, approximately 11:27–11:34 AM America/Chicago.
These observations are a snapshot. Recheck live state before each operation.

## Execution rules

- Complete host hardening before guest hardening. Apply one reviewed domain at a time.
- Recheck dependencies, create rollback steps, and validate health after each change.
- Keep secrets and local machine configuration out of tracked files.
- Commit completed implementation changes separately per project. Never push.
- Obtain exact approval for protected TrueNAS operations under [truenas/AGENTS.md](truenas/AGENTS.md).

## Atlas reboot request

- [x] Obtain explicit authorization to reboot Atlas only.
- [x] Recheck guest placement, HA maintenance, quorum, replication, active tasks, and boot configuration.
- [x] Assess two-node quorum loss and HA fencing before issuing the reboot.
- [x] Use the supported HA disarm procedure before temporary quorum loss.
- [ ] Verify an independent console recovery path for future maintenance.
- [x] Reboot only if the safety checks pass, then verify the kernel, pools, cluster, HA, and guest health.

Atlas was in HA maintenance mode. All running guests were on Prometheus.
VM 122 on Atlas was stopped. Kernel `7.0.14-20-pve` was installed, while `7.0.14-19-pve` was running.
The cluster required two votes. An Atlas reboot can remove quorum and affect HA behavior on Prometheus.
Authorization does not permit changes to expected votes, guest startup, or unrelated hardening.
Budget 5–15 minutes for the reboot and validation after the safety checks pass.

## Atlas reboot result — October 4, 2026

The user authorized the reboot after safety checks. Atlas rebooted at approximately 11:44 AM CDT and returned by 11:48 AM CDT.

- [x] Confirm no running Atlas guests or active host tasks before the reboot.
- [x] Verify healthy pools, recent replication, both EFI boot entries, and the new kernel files.
- [x] Disarm HA in freeze mode and verify the CRM and Prometheus LRM watchdogs were released.
- [x] Verify Atlas returned on kernel `7.0.14-20-pve` with a different boot ID.
- [x] Restore HA protection after both nodes regained quorum.

Prometheus retained the same boot ID. All 29 running guests retained placement, state, and increasing uptime.
VM 122 remained stopped. Atlas remained in its existing HA maintenance mode.
Both nodes reported healthy pools. Atlas reported all seven checked Proxmox services active and no failed systemd units.
Replication resumed successfully after the reboot. Expected votes remained two throughout maintenance.
HA protection was temporarily suspended during the reboot. No guest restart was observed.
Independent console access was not tested. This remains an open recovery prerequisite for future maintenance.

The maintenance procedure follows the supported [Proxmox HA disarm and re-arm workflow](https://github.com/proxmox/pve-docs/blob/master/ha-manager.adoc#disarming-ha-for-cluster-maintenance).

## Atlas maintenance removal and Minecraft migration — October 4, 2026

The user authorized maintenance removal and migration of the five existing Minecraft servers to Atlas.

- [x] Verify Atlas capacity, storage availability, replication health, and existing Minecraft services.
- [x] Remove Atlas HA maintenance mode through the supported HA command.
- [x] Migrate containers 113, 115, 116, 120, and 124 through HA management.
- [x] Verify all five Minecraft services finish startup and answer game status requests.
- [x] Verify final quorum, HA protection, guest placement, and replication health.

| VMID | Minecraft server | Destination |
| --- | --- | --- |
| 113 | atm10-nash | Atlas |
| 115 | homestead-nash | Atlas |
| 116 | yabu-nash | Atlas |
| 120 | bettermc-nash | Atlas |
| 124 | hewwo-pwincess | Atlas |

Each container restarted during its migration. Incremental ZFS transfers used existing replication copies.
Removing maintenance allowed existing HA policies to return Radarr, Vaultwarden, and NexDeck to Atlas.
The existing HA load balancer also moved Bambuddy to Atlas and later returned it to Prometheus. These were automatic HA movements.
The HA load balancer moved Homestead back to Prometheus after its first migration.
Automatic balancing was disabled for Homestead and YABU, then Homestead returned to Atlas.
The other three Minecraft containers already had automatic balancing disabled.
All five servers answered Minecraft status requests by approximately 12:01 PM CDT.
Their replication jobs completed successfully toward Prometheus with zero failures.
Atlas maintenance is disabled. Quorum is healthy, and HA fencing is armed.
VM 122 remains stopped. No modpack, network, or backup schedule was changed.

## Host inventory

| Host | Platform | State at discovery |
| --- | --- | --- |
| Prometheus | PVE 9.2.21, Debian 13 | 29 running containers, pools ONLINE |
| Atlas | PVE 9.2.21, Debian 13 | HA maintenance, VM 122 stopped, pools ONLINE |
| Mnemosyne | PBS 4.2.7, Debian 13 | Datastore `mneme`, pools ONLINE |
| Erebus | TrueNAS 25.10.4 | Pool `gaia` healthy, 28 datasets, three SMB shares, seven NFS exports |

Erebus apps: Cobalt, Tdarr, SABnzbd, Plex, LANCache, Threadfin, FastChannels, spotDL, and Lidarr. All reported RUNNING.

## Host tasks

P0 means prerequisite. P1 means high priority. P2 means subsequent hardening.
Time estimates exclude large restore or offsite transfers.

- [ ] **H1 / P0 / Establish recovery and maintenance prerequisites (60–120 minutes, restore transfer time additional).**
  - [ ] Test independent console access. Capture protected configuration backups before mutation. Validate one isolated guest restore.
  - [ ] Confirm Atlas maintenance purpose, migration capacity, replication freshness, NFS clients, trusted admin sources, and current backup windows.
  - [ ] Assess a third quorum vote. Do not alter expected votes as a hardening shortcut.
  - **Complete when:** documented recovery path, verified restore, reviewed access/dependency map, and a safe one-host maintenance plan.

- [ ] **H2 / P1 / Restrict PVE and PBS management access (90–150 minutes).**
  - [ ] Define allowlists for SSH, PVE 8006, PBS 8007, migration, replication, consoles, corosync, monitoring, and required storage traffic.
  - [ ] Include IPv6. Stage and validate rules on one host with independent console access and a timed recovery procedure.
  - [ ] Restrict or remove RPC and other listeners only after dependency checks. Preserve required PVE proxy and routing functions.
  - **Complete when:** trusted administration, clustering, replication, consoles, and backups work. Untrusted sources fail explicit reachability tests.

- [ ] **H3 / P1 / Harden host authentication and patch maintenance (90–180 minutes, maintenance window separate).**
  - [ ] Prove key access for administration, Ansible, inter-node SSH, backups, and emergency access before disabling password SSH.
  - [ ] Preserve required root key authentication for supported cluster workflows. Disable unused forwarding features after dependency checks.
  - [ ] Audit PVE/PBS MFA enforcement, token scopes, certificate validity, time synchronization, and account ownership.
  - [ ] Refresh package metadata during the implementation phase. Review updates and kernel changes, then reboot one host at a time.
  - **Complete when:** repeat key-authentication tests, expected MFA behavior, valid TLS, current reviewed packages/kernel, and healthy quorum after maintenance.

- [ ] **H4 / P1 / Protect PBS recovery data from compromised clients (90–150 minutes, offsite transfer additional).**
  - [ ] Move retention enforcement from backup clients to PBS. Remove client prune permissions only after retention simulation and a successful backup trial.
  - [ ] Use namespace-scoped identities. Separate writer, verifier, restore, and maintenance privileges. Preserve existing owners and access dependencies.
  - [ ] Verify recent completed verification jobs. Test protected recovery points and an independently controlled offsite copy for cluster-nash.
  - [ ] Create reviewed local PBS inventory before using its project. Do not apply MainStore or backup/pbs defaults to mneme.
  - **Complete when:** the backup writer cannot prune recovery points, scheduled retention matches the reviewed policy, and independent recovery works.

- [ ] **H5 / P1 / Harden TrueNAS access and data protection (2–4 hours, backup copy additional).**
  - [ ] Map NFS clients and UID/GID requirements. Replace empty restrictions with explicit clients. Review root mappings per export.
  - [ ] Confirm FTP consumers. Disable FTP if unused, or replace cleartext access with a reviewed secure method.
  - [ ] Validate the UI certificate and HTTPS path before enforcing HTTPS. Configure and test administrator MFA and recovery access.
  - [ ] Replace the root-owned dashboard credential with supported limited privileges, if this TrueNAS version permits them.
  - [ ] Design snapshots, retention, and independent backups for appdata and important datasets. Reconcile desired-state drift before convergence.
  - [ ] Exact TrueNAS storage, network, SSH, and Ansible-account changes require explicit approval under truenas/AGENTS.md.
  - **Complete when:** approved clients retain NFS/SMB/app access, unapproved clients fail, TLS/MFA work, and recovery coverage is verified.

## H1/P0 progress — October 4, 2026

Status: **in progress**. Recovery backups and one isolated guest restore passed.
Console display tests and the complete administrator access tests remain open.
No firewall, authentication, quorum, NAS sharing, or production placement changes occurred during H1.

### Recovery evidence

- [x] Capture protected configuration archives for Atlas, Prometheus, Mnemosyne, and Erebus.
- [x] Validate readable archives, expected configuration members, restrictive permissions, and SHA-256 checksums.
- [x] Restore one guest from PBS to an isolated test container and validate its application data.
- [x] Confirm current HA protection, quorum, peer replication, migration capacity, and backup schedules.
- [ ] Test authenticated console display for each host. Confirm local console access for Erebus.
- [ ] Validate administrator reachability from the LAN and each named Tailscale device.
- [ ] Review the maintenance plan and select an independent quorum witness, if desired.

Protected artifacts are local, ignored, and credential-bearing. Do not commit or publish them.
Directory: `truenas/artifacts/h1-recovery-20261004/`, mode `0700`; archives and database exports use mode `0600`.
PVE archives include `/etc/pve`, host networking, SSH, boot settings, and package sources.
Consistent SQLite exports supplement the raw PVE configuration databases in the archives. Both exports passed SQLite integrity checks.
PBS includes `/etc/proxmox-backup`, networking, SSH, boot settings, and package sources.
TrueNAS uses supported `config.save` with the secret seed and root authorized keys. Pool encryption keys were not requested.
These are configuration backups, not host disk images or appdata backups. Configuration import was not tested.
The only recorded copy is on this controller. Place an encrypted copy in independent recovery storage before disruptive hardening.

Spoolman CT 102 restored from `mnemosyne:backup/ct/102/2026-10-04T11:31:56Z` to CT 132 on Prometheus `local-zfs`.
The next free cluster ID was 114, but the ignored Minecraft inventory still references 114. CT 132 follows the highest current ID.
Restore processed 2.567 GiB in approximately 60 seconds, with a 50 MiB/s transfer limit.
The clone remained stopped until its network interface was removed. It had no bind mounts or hook script.
It started with loopback only, no routes, no HA registration, and automatic boot disabled.
SQLite integrity returned `ok`. Nine database tables were present. Spoolman returned HTTP 200 and read 13 spool records.
The user explicitly authorized cleanup after the successful test. CT 132 and its `local-zfs` disk were deleted.
Pre-deletion checks confirmed the test hostname, stopped state, expected disk, no network or mount entries, and no HA registration.
Post-deletion checks confirmed that CT 132 and its disk are absent. Production CT 102 remains running. PBS backups were not deleted.
Production Spoolman was not stopped or modified. The restore proves this snapshot, not every guest or backup.

### Console and administrator paths

| Host | Recovery path | Evidence |
| --- | --- | --- |
| Atlas | Management controller `10.10.10.22` | HTTPS responds; authenticated console display pending |
| Prometheus | Management controller `10.10.10.15` | HTTPS timed out from this controller; user reports connection works; console display pending |
| Mnemosyne | Management controller `10.10.10.13` | HTTPS responds; authenticated console display pending |
| Erebus | Physical keyboard, mouse, and local display | User reports physical access; display/login test pending |

The management controllers use the routed management VLAN. A switch or routing failure can still prevent remote access.
The TrueNAS physical console provides a local recovery path. Confirm physical alternatives for the other hosts before network changes.
HTTPS reachability checks bypassed certificate validation solely for discovery. They do not prove trusted TLS or remote console operation.

Required administrator sources supplied by the user:

| Source | Address |
| --- | --- |
| LAN | `192.168.1.0/24` |
| iPhone | `100.76.184.65` |
| iPad | `100.75.92.43` |
| Laptop | `100.66.52.114` |

Tailscale router CT 123 advertises the LAN, management, storage, PVE, and guest networks.
Its guest address is `10.10.40.88`, and its Tailscale address is `100.110.0.35`. Its `NoSNAT` setting is false. Destination hosts can see the router address instead of each device's Tailscale address.
H2 must test the actual source address and preserve the routed path. Tailnet device addresses alone are insufficient as host allowlists.
Tailnet ACLs and route approvals were not independently inspected.

### Dependencies and maintenance plan

At recheck, Atlas runs eight production containers and Prometheus runs 21. VM 122 remains stopped.
All 30 replication jobs reported successful recent syncs and zero failures, around noon CDT.
Combined running guest allocations are 130 GiB RAM and 66 virtual CPUs. Each host has approximately 376 GiB RAM.
Both hosts have substantial free `helios` and `tartarus` capacity. These checks support evacuation, subject to per-guest constraints and a fresh preflight.
The five Minecraft containers retain Atlas placement. A future evacuation restarts LXCs and interrupts game sessions.
CT 124 retains CPU pinning and NUMA constraints. Recheck destination compatibility before any migration.
CTs 130 and 131 lack HA entries and require explicit handling during evacuation. The temporary recovery test CT 132 was deleted after explicit approval.

Corosync currently uses `10.10.30.3` and `10.10.30.9` over the management bridge.
Dedicated `10.10.50.x` interfaces are DOWN on both nodes. Do not restrict management traffic based on the intended dedicated-link inventory.
PVE storage access uses `10.10.20.4` and `10.10.20.9`. PBS is `10.10.20.2`; TrueNAS storage is `10.10.20.3`.
PVE hosts showed no active NFS mounts. NFS mounts reside inside privileged media containers.

| Guest | Verified NFS dependencies on Erebus |
| --- | --- |
| 108 Deluge | `/mnt/gaia/downloads/torrent` |
| 109 SABnzbd | `/mnt/gaia/downloads/nzb` |
| 110 Sonarr | `/mnt/gaia/media/tv`, `/mnt/gaia/media/anime`, `/mnt/gaia/downloads` |
| 111 Radarr | Movies, anime, downloads, and nested NZB/torrent mounts |

TrueNAS publishes torrent, complete/incomplete NZB, TV, anime, downloads, and movies exports.
Some mounted paths are child directories of parent exports. Preserve parent exports and client UID/GID behavior until H5 reviews them.
Media services depend on Erebus. PBS backup and restore depend on Mnemosyne.
Remote Tailscale administration depends on CT 123 and its current PVE host.
The core Arista switch routes these VLANs. Its management changes are outside this task.

General backups run every six hours at minute 30, next approximately 6:30 PM CDT on this date.
Minecraft backups run hourly at minute zero. The noon Atlas backup was still active during this assessment.
No maintenance should overlap an active backup, restore, replication, scrub, or migration task.

Proposed one-host maintenance sequence, to execute only for an authorized change:

1. Test the target console and create fresh protected configuration backups. Confirm recovery credentials remain available without the guest identity services.
2. Confirm both nodes, HA, storage, NFS, backups, and peer replicas are healthy. Check target capacity and every guest constraint.
3. Evacuate the target through reviewed HA maintenance and migration operations. Handle non-HA guests explicitly. Confirm the target has no running guests.
4. For quorum loss without a witness, use supported HA disarm in freeze mode. Verify watchdog release before the authorized host shutdown.
5. Restore the host, verify quorum and health, and re-arm HA. Remove maintenance and restore reviewed guest placement. Verify applications and backup completion.

If a safety gate fails, stop before shutdown. If a host fails to return, use its verified console and prior boot kernel.
Do not reduce expected votes or start duplicate guest copies. Keep the surviving host running and restore the failed host before re-arming HA.
PVE configuration recovery needs a separate reviewed procedure. Do not copy raw cluster databases over a running cluster.
PBS and Erebus maintenance require separate application/storage outage plans; do not reboot them with PVE maintenance.

### Third vote assessment

The cluster has two votes and needs both. No external witness exists.
A supported QDevice on an independent, always-on server can provide a third vote for this two-node cluster.
Prefer a small dedicated server outside the PVE guests. Mnemosyne is physically independent, but would couple backup and quorum availability.
Confirm independent power, network reachability, TCP 5403, ownership, and recovery access before selecting a witness.
No witness packages were installed and no quorum settings changed.
Reference: [Proxmox external vote documentation](https://github.com/proxmox/pve-docs/blob/master/pvecm.adoc).

## Guest tasks

- [ ] **G1 / P1 / Establish the guest baseline (90–150 minutes).**
  - [ ] Pilot one low-risk container. Prove key access, restrict SSH/admin ports, retain IPv6 policy, and enforce only the reviewed service dependencies.
  - [ ] Inspect current OS support and application update methods. Review Debian 12 guests 103, 106, and 119 separately.
  - **Complete when:** application and backup health pass, permitted clients succeed, denied clients fail, and the Ansible repeat run reports no changes.

- [ ] **G2 / P1 / Reduce privileged media-container access (2–4 hours).**
  - [ ] Prioritize 108–111. Trace broad device grants and serial/USB mounts. Remove only proven unnecessary capabilities and device access.
  - [ ] Evaluate supported host-managed mounts or VM isolation before any privileged-to-unprivileged conversion. Preserve media ownership and mount ordering.
  - **Complete when:** NFS, imports, downloads, VPN, application access, and backup/restore tests pass after each scoped change.

- [ ] **G3 / P1 / Harden proxy, identity, and secret-bearing services (2–4 hours).**
  - [ ] Prioritize NPM 101, Pocket ID 100, Vaultwarden 125, Forgejo 103, and dashboards 129/131.
  - [ ] Diagnose failed Certbot renewal. Verify active certificates, external routes, authentication, admin endpoints, registration settings, and credential scopes.
  - [ ] Restrict direct backend access where dependencies permit. Preserve required bootstrap/recovery authentication.
  - **Complete when:** intended public routes and authentication work, admin interfaces require trusted access, and renewals succeed.

- [ ] **G4 / P2 / Reduce service privileges across remaining applications (3–6 hours).**
  - [ ] Use dedicated users where supported. Add tested systemd restrictions individually, starting with root services and sensitive data paths.
  - [ ] Review TrueNAS app images, privileges, host networking, writable mounts, and published ports. Pin mutable images through their deployment owners.
  - [ ] Inspect Deluge VPN behavior, Minecraft RCON/web-map ports, Tailscale route/ACL scope, monitoring authentication, and unused services.
  - [ ] Assess VM 122 internally during a separately reviewed startup window. Do not start it merely for discovery.
  - **Complete when:** functional tests cover each service, required integrations remain operational, and update/backup paths still work.

- [ ] **G5 / P2 / Record and maintain the baseline (60–120 minutes).**
  - [ ] Encode reviewed controls in opt-in Ansible roles. Use scoped project commits, lint, syntax checks, meaningful dry-runs, and repeat-run validation.
  - [ ] Add alerts for backup/verification failures, certificate renewal, failed services, and configuration drift.
  - [ ] Schedule periodic restore and access tests only when requested. Keep machine-specific inventory and secrets ignored.
  - **Complete when:** reviewed changes have reproducible deployment, rollback steps, validation evidence, and accountable exceptions.

## Guest inventory

26 containers run Debian 13. Three run Debian 12. All running containers reside on Prometheus, VLAN 40.

| VMID | Guest | Host | State | OS | Privilege |
| --- | --- | --- | --- | --- | --- |
| 100 | pocketid-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 101 | npm-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 102 | spoolman-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 103 | forgejo-nash | prometheus | running | Debian 12 (bookworm) | unprivileged |
| 104 | prowlarr-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 105 | homebridge-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 106 | apt-nash | prometheus | running | Debian 12 (bookworm) | unprivileged |
| 107 | pxe-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 108 | deluge-nash | prometheus | running | Debian 13 (trixie) | privileged (NFS) |
| 109 | sabnzbd-nash | prometheus | running | Debian 13 (trixie) | privileged (NFS) |
| 110 | sonarr-nash | prometheus | running | Debian 13 (trixie) | privileged (NFS) |
| 111 | radarr-nash | prometheus | running | Debian 13 (trixie) | privileged (NFS) |
| 112 | searxng-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 113 | atm10-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 115 | homestead-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 116 | yabu-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 117 | seerr-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 118 | openwebui-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 119 | git-mirror-nash | prometheus | running | Debian 12 (bookworm) | unprivileged |
| 120 | bettermc-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 121 | diun-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 122 | hytale-nash | atlas | stopped | unverified Linux guest | VM |
| 123 | tailscale-router-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 124 | hewwo-pwincess | prometheus | running | Debian 13 (trixie) | unprivileged |
| 125 | vaultwarden-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 127 | loki-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 128 | bambuddy-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 129 | nexdeck-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 130 | speedtest-nash | prometheus | running | Debian 13 (trixie) | unprivileged |
| 131 | homelable-nash | prometheus | running | Debian 13 (trixie) | unprivileged |

## Findings from discovery

PVE 9.2.21 on both hosts. Cluster quorate, two votes required, no third vote reported.

Atlas HA maintenance remains active. 27 containers and VM 122 have HA entries. Containers 130 and 131 have no HA entry.

All 30 replication jobs report zero failures and successful recent synchronization.

Both PVE firewalls report disabled/running. Legacy filter policies accept traffic. nft rulesets are empty on PVE/PBS.

PVE and PBS host defaults permit root login and password authentication.

Kernel 7.0.14-20-pve is installed on all three Debian hosts. Running kernels are older. No reboot occurred.

Cached apt lists show no pending upgrades. Package metadata was not refreshed. This does not establish current security patch status.

Container configs with firewall=1: 107.

Four privileged containers: 108 Deluge, 109 SABnzbd, 110 Sonarr, 111 Radarr. All use NFS.

Each has lxc.cgroup2.devices.allow: a and an empty lxc.cap.drop setting, plus serial/USB passthrough.

These permissions require individual investigation. Do not switch privilege modes or remove NFS support blindly.

Root service examples: npm.service, sabnzbd.service, deluge-web.service.

Most inspected application units lack NoNewPrivileges and ProtectSystem. Vaultwarden and Grafana already have these protections.

NPM certbot.service is failed. No failed units reported by the other inspected containers.

PBS datastore mneme at /mneme. Daily verification, pruning, and garbage collection are configured.

General PVE backups run every six hours. The five Minecraft guests have hourly backups.

Recent Minecraft backup and prune tasks report OK. Backup directories exist today. Full restore tests remain pending.

backup-nash@pbs has DatastorePowerUser on cluster-nash. Backup tasks actively prune with this identity.

PBS imports cluster-bldr weekly. This is not proof that cluster-nash has an independent offsite copy.

PVE retention policies and PBS daily pruning differ. Simulate effective retention before changing permissions or schedules.

TrueNAS global MFA is disabled. FTP is active without TLS. The UI permits HTTP without automatic HTTPS redirection.
Six NFS exports have empty client restrictions. Three map all users to root.
A certificate expiration alert exists. The active UI certificate still requires verification.
The NexDeck API key belongs to root and has no expiration.
No periodic snapshot or replication tasks appeared in TrueNAS middleware. Manual snapshots were not enumerated.

## Assessment limits

WAN exposure, router ACLs, inter-VLAN reachability, IdP MFA, and full restore reliability remain unverified.
SSH results describe daemon defaults. Match rules need separate checks.
VM 122 remained stopped. Its internal OS and security state remain unverified.
An installed newer kernel does not prove that the bootloader selects it.

## References

- [Proxmox firewall documentation](https://github.com/proxmox/pve-docs/blob/master/pve-firewall.adoc)
- [PBS storage and ransomware protection](https://pbs.proxmox.com/docs/storage.html)
- [TrueNAS security recommendations](https://www.truenas.com/docs/solutions/optimizations/security/)
