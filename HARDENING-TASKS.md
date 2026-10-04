# Homelab hardening task list

Status: inventory complete. Atlas reboot and Minecraft container migrations completed on October 4, 2026.
All five Minecraft servers passed service startup and LAN game status checks. H1/P0 and H2/P1 are complete with the validation limits documented below. H3/P1 is in progress. Other hardening tasks have not started.

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
- [x] Verify host remote consoles for future maintenance (user confirmed October 4; routed management remains a shared dependency).
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
Independent console access was not tested during the reboot. The user subsequently confirmed that the remote consoles work during H1/P0.

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

- [x] **H1 / P0 / Establish recovery and maintenance prerequisites (60–120 minutes, restore transfer time additional).**
  - [x] Verify PVE/PBS remote consoles (user confirmation), capture protected configuration backups, and validate one isolated guest restore.
  - [x] Confirm the Erebus physical display/login path (user confirmed October 4, 2026).
  - Remote PVE/PBS consoles share the routed management network. Physical alternatives remain unverified; switch/routing changes require a separate recovery plan.
  - [x] Confirm Atlas maintenance ended after the reboot, migration capacity, replication freshness, NFS clients, trusted admin sources, and backup windows.
  - [x] Assess a third quorum vote. No witness was selected or installed. Expected votes remain unchanged.
  - **Complete when:** documented recovery path, verified restore, reviewed access/dependency map, and a safe one-host maintenance plan.

- [x] **H2 / P1 / Restrict PVE and PBS management access (90–150 minutes).**
  - [x] Define and apply allowlists for SSH, PVE 8006, PBS 8007, migration, replication, consoles, corosync, dashboard discovery, and required storage traffic.
  - [x] Include IPv6. Pilot Atlas with verified console access and a 15-minute rollback timer, then validate Prometheus and PBS separately.
  - [x] Block inbound RPC and unused host listeners after dependency checks. Preserve trusted PVE console/proxy access and forwarding. Services were not removed.
  - **Complete when:** trusted administration, clustering, replication, consoles, and backups work. Untrusted sources fail explicit reachability tests.

- [ ] **H3 / P1 / Harden host authentication and patch maintenance (90–180 minutes, maintenance window separate).**
  - [x] Prove controller and Ansible key access on all three hosts, pinned inter-node SSH in both directions, and protected console recovery before disabling password SSH. PBS backups use their existing pinned API identity.
  - [x] Preserve root key authentication and TCP forwarding. Disable password/interactive SSH, X11 forwarding, and agent forwarding after dependency checks.
  - [x] Audit PVE/PBS MFA enforcement, token scopes, certificate validity, time synchronization, and account ownership.
  - [ ] Enroll and verify local administrator MFA. Resolve the certificate policy and hostname access.
  - [x] Refresh package metadata. Review updates and kernel changes. Reboot Prometheus and PBS separately after safety checks, then validate services and recovery access.
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

Status: **complete for host hardening preparation**. Recovery backups and one isolated guest restore passed.
The user confirmed that all remote consoles work and that the Erebus physical console displays the host and permits login.
The user confirmed that the iCloud bundle opens and downloads from another device.
The user confirmed administrator access through every required LAN and Tailscale path.
The maintenance plan was reviewed against the recorded quorum, replication, placement, capacity, and dependency evidence.
Recheck live state before each change. This completion does not authorize a reboot, switch change, or the next hardening phase.
No firewall, authentication, quorum, NAS sharing, or production placement changes occurred during H1.

### Recovery evidence

- [x] Capture protected configuration archives for Atlas, Prometheus, Mnemosyne, and Erebus.
- [x] Validate readable archives, expected configuration members, restrictive permissions, and SHA-256 checksums.
- [x] Copy the recovery bundle to personal iCloud and confirm access from another device through user verification.
- [x] Restore one guest from PBS to an isolated test container and validate its application data.
- [x] Confirm current HA protection, quorum, peer replication, migration capacity, and backup schedules.
- [x] Verify Atlas, Prometheus, and Mnemosyne remote consoles through user confirmation on October 4, 2026.
- [x] Confirm physical display/login access for Erebus through user confirmation on October 4, 2026.
- Recovery limitation: PVE/PBS remote consoles depend on routed management. Independent physical alternatives are not verified.
- [x] Validate administrator access from the LAN and each named Tailscale device through user confirmation.
- [x] Review the one-host maintenance plan and assess an independent quorum witness. Witness deployment remains a separate decision.

Protected artifacts are local, ignored, and credential-bearing. Do not commit or publish them.
Directory: `truenas/artifacts/h1-recovery-20261004/`, mode `0700`; archives and database exports use mode `0600`.
PVE archives include `/etc/pve`, host networking, SSH, boot settings, and package sources.
Consistent SQLite exports supplement the raw PVE configuration databases in the archives. Both exports passed SQLite integrity checks.
PBS includes `/etc/proxmox-backup`, networking, SSH, boot settings, and package sources.
TrueNAS uses supported `config.save` with the secret seed and root authorized keys. Pool encryption keys were not requested.
These are configuration backups, not host disk images or appdata backups. Configuration import was not tested.
The user selected personal iCloud Drive and reports end-to-end encryption enabled and Apple Account MFA required.
A verified bundle was copied to `iCloud Drive/Homelab Recovery/homelab-h1-recovery-20261004.tar.gz`.
The local iCloud copy matches the source byte-for-byte and uses mode `0600`.
SHA-256: `355c2ffadb1748b9080b9ea2515e823db3245b9f506d2e59efe99942950b273a`.
The bundle contains the four configuration archives, two consistent PVE database exports, and the checksum manifest.
It excludes the temporary TrueNAS download token. The archive relies on the user-reported iCloud encryption; it has no separate archive password.
The user confirmed that the bundle opens and downloads from another device on October 4, 2026.
This confirms cloud availability. Configuration import remains untested.
Keep Apple Account recovery available independently of homelab identity services.

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
| Atlas | Management controller `10.10.10.22` | HTTPS responds; user confirms remote console works |
| Prometheus | Management controller `10.10.10.15` | HTTPS timed out from this controller; user confirms access and remote console work |
| Mnemosyne | Management controller `10.10.10.13` | HTTPS responds; user confirms remote console works |
| Erebus | Physical keyboard, mouse, and local display | User confirms physical console display and login work |

The management controllers use the routed management VLAN. A switch or routing failure can still prevent remote access.
The TrueNAS physical console provides a local recovery path. Confirm physical alternatives for the other hosts before network changes.
HTTPS reachability checks bypassed certificate validation solely for discovery. They do not prove trusted TLS. Remote console functionality is user-confirmed, not independently tested by this agent.

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

Administrator access test evidence, October 4, 2026:

- [x] iPhone Tailscale reachability to Atlas: user confirmed after the cellular/Tailscale test request.
- [x] Confirm authenticated administrator login to Atlas through the iPhone Tailscale path: user confirmed.
- [x] Verify Prometheus, PBS, and TrueNAS administrator login through the same iPhone Tailscale connection: user confirmed.
- [x] Verify all four administrator interfaces from the LAN, laptop Tailscale, and iPad Tailscale paths: user confirmed access through all required addresses.

The final confirmation followed the administrator login test request. Results are user-reported, not independently observed by this agent.

Connection success does not by itself establish successful administrator authentication.


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

## H2/P1 result — October 4, 2026

Status: **complete**. The user authorized implementation after H1/P0.
Both PVE hosts now enforce native `pve-firewall` host rules. PBS enforces an `inet` nftables input policy.
All policies deny other new host connections. Existing connections, loopback, and required ICMP/ICMPv6 remain permitted.
Outbound traffic and guest forwarding remain permitted. No guest firewall gate was enabled.

### Applied access policy

| Source | Permitted host traffic |
| --- | --- |
| LAN `192.168.1.0/24`, router `10.10.40.88`, three named Tailscale device addresses | PVE TCP 22, 8006, 3128, 5900–5999; PBS TCP 22, 8007 |
| PVE management/storage addresses `.30.3`, `.30.9`, `.20.4`, `.20.9` | PVE TCP 22, 8006, 60000–60050; PBS TCP 8007 |
| PVE management addresses `10.10.30.3`, `10.10.30.9` | PVE UDP 5404–5412 for cluster traffic |
| NexDeck `10.10.40.42`, Homelable `10.10.40.7` | PVE TCP 8006 and PBS TCP 8007 |
| Other IPv4/IPv6 sources | No new host management connections; diagnostic ICMP/ICMPv6 remains allowed |

Tailscale administration currently arrives through the trusted subnet router because SNAT is enabled.
A compromised trusted router can reach management interfaces. Tailnet ACL review remains part of the guest/network scope.
The named Tailscale addresses are also permitted if they arrive without translation. No IPv6 administrator source was requested.
RPC port 111, BFD listeners, and other unused inbound host ports are blocked, including from administrator sources.
The host storage clients initiate their requests outbound. Established replies remain permitted.
TrueNAS host access and sharing were not changed.

PVE paths: `/etc/pve/firewall/cluster.fw` and `/etc/pve/nodes/<node>/host.fw`.
The cluster gate is enabled. Both host gates are enabled. All 30 guest firewall gates remain disabled.
CT 107 retains its existing interface firewall flag, but its guest firewall gate remains disabled.
An explicit final host DROP precedes the native automatic management exceptions. This prevents the whole management subnet from inheriting access.
The installed iptables backend remains in use. No backend switch or guest restart occurred.

PBS paths: `/etc/homelab-host-firewall.nft` and `/etc/systemd/system/homelab-host-firewall.service`.
The service is active and enabled. It owns only `table inet homelab_management`.
Its start/reload replaces that table atomically. Its stop removes only that table. It does not flush unrelated rules.
Native PVE persistence and the enabled PBS service preserve the policy at boot. Reboot persistence was not tested.

### Validation evidence

- [x] Confirm all 30 guest firewall gates are off before cluster activation. Confirm no guest firewall configuration files exist.
- [x] Parse and compile native PVE rules. Check PBS nftables syntax and validate the systemd unit.
- [x] Verify fresh controller SSH and API reachability on all three hosts. Unauthenticated API probes returned the expected HTTP 401.
- [x] Verify router CT 123 can reach management ports. Verify NexDeck can reach each permitted host API.
- [x] Verify untrusted Spoolman CT 102 cannot reach host SSH, API, SPICE, or RPC ports as applicable.

#### Cluster, backups, and applications

- [x] Verify IPv6 SSH/API denial over live link-local connections on all three hosts. IPv6 ping and neighbor discovery continue to work.
- [x] Verify both peer SSH directions using Proxmox's pinned host-key configuration.
- [x] Verify quorum and armed HA. Run existing replication jobs 102-0 and 111-0 successfully after activation, one per direction.
- [x] Verify scheduled PBS backups completed successfully after activation. Examples include CTs 108, 109, and 129.
- [x] Verify all five Minecraft servers still answer valid game status requests.

#### Administrator checks and finalization

- [x] Verify user-reported fresh Tailscale administrator login and guest console on Atlas. The user also confirmed the requested Prometheus/PBS access and console checks.
- [x] Cancel all rollback timers after successful validation. Keep persistent rules enabled.
- [x] Run repository-required `ansible-lint --offline` in `proxmox/`: zero failures and zero warnings, 193 files processed.

The native PVE simulator accepts IPv4 only on these hosts. IPv6 validation used actual sockets and neighbor connectivity instead.
Corosync peer acceptance and untrusted denial passed native rule simulation. Untrusted migration access also simulated DROP.
The native simulator could not parse the accepted migration multiport rule. Live temporary listeners verified TCP 60000 and 60050 in both directions.
The temporary listeners exited after the probes. No production guest was migrated merely to test the firewall.
A generic inter-node SSH attempt failed host-key verification. The supported Proxmox host-key options passed without changing known hosts.
The running scheduled backup continued during the host-input policy change. Established transfers were preserved, and later backup tasks completed successfully.
The full scheduled backup batch had not yet completed when these individual successes were inspected.
No Ansible implementation files changed. Reusable, opt-in automation remains in G5. Machine-specific firewall configurations are ignored artifacts.

### Recovery and implementation record

Each activation had a local 15-minute rollback timer. PVE timers called `pve-firewall stop`; PBS called `systemctl stop homelab-host-firewall.service`.
The cluster-gate activation also had a timer to disable that gate. All timers were cancelled after the checks passed.
Automatic approval review initially rejected cluster activation because it could affect guests and clustering.
Read-only checks then proved all guest gates were disabled. Both host gates were explicitly disabled before retrying the inert cluster gate.
The protected retry passed approval review. Atlas was then the only filtered host during the pilot.

Pre-change PVE artifacts remain under `/root/h2-recovery-20261004/` on Prometheus.
PBS pre-change artifacts remain under that path on Mnemosyne.
Protected current configuration copies are ignored under `truenas/artifacts/h2-firewall-20261004/` on this controller.
Do not commit those machine-specific files.

For emergency recovery through a verified console:

1. On an affected PVE host, run `pve-firewall stop` to remove its active rules locally.
2. With quorum available, set that node's host firewall option to disabled before restarting its firewall service.
3. On PBS, stop and disable `homelab-host-firewall.service` to remove its owned table and prevent automatic activation.
4. Inspect the saved pre-change artifacts before any restoration. Do not overwrite unrelated cluster configuration.
5. Correct the scoped policy and repeat the trusted, denied, console, quorum, replication, and backup checks before activation.

Reference: [Proxmox native host firewall documentation](https://raw.githubusercontent.com/proxmox/pve-docs/master/pve-firewall.adoc).

### Management subdomain access correction — October 4, 2026

The user identified `pve.wbreiler.com` and `pbs.wbreiler.com` as the primary external administration paths.
The original H2 allowlist omitted NPM CT 101. Its verified address is `10.10.40.86`.
Both NPM backend connections timed out before correction.

The user authorized restoring these paths. Persistent exceptions now allow only:

- NPM `10.10.40.86` to Atlas TCP 8006 for `pve.wbreiler.com`.
- NPM `10.10.40.86` to PBS TCP 8007 for `pbs.wbreiler.com`.

PVE firewall compilation and PBS nftables syntax validation passed. PBS reloaded its own table atomically.
Both backend connections now succeed. SSH from NPM remains blocked on both hosts.
An unrelated guest remains blocked from both management APIs.
Protected pre-change copies are under `/root/h3-recovery-20261004/` on the respective hosts.

Both subdomain routes returned HTTP 200 through NPM with forced local resolution.
NPM presents an expired certificate. Normal certificate verification failed.
The routing-only probes disabled certificate verification and sent no credentials. They do not prove trusted TLS. The user subsequently confirmed both subdomains open externally.
No DNS, certificate, Cloudflare setting, or application authentication changed.
The proxy certificate requires separate repair. H3 remains incomplete.

## H3/P1 progress — October 4, 2026

Status: **in progress**. Host SSH hardening, authentication audit, package refresh, and maintenance preflight are complete.
Local administrator MFA enrollment and certificate policy selection remain pending. The authorized kernel maintenance is complete.
The user confirmed that normal Pocket ID login uses a passkey.

### SSH changes and evidence

All three hosts use `/etc/ssh/sshd_config.d/00-homelab-hardening.conf` with these settings:

```text
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
X11Forwarding no
AllowAgentForwarding no
```

TCP forwarding remains enabled for supported Proxmox workflows. Root key login remains enabled.
The repository had no agent-forwarding requirement. SSH changes did not alter web account passwords or MFA settings.

- [x] Test fresh controller access with only `cluster.pub` and its SSH agent key on each host before and after mutation.
- [x] Test peer key-only SSH in both directions with Proxmox's pinned host-key options.
- [x] Validate daemon syntax and effective root settings for LAN/Tailscale source contexts. Reload SSH without restarting the host.
- [x] Verify each server offers only `publickey`; password/keyboard-interactive-only attempts fail without submitting credentials.
- [x] Execute Ansible ping modules successfully on all three hosts after hardening. No deployment roles ran.

Each host had a protected `/root/h3-recovery-20261004/ssh-before.tar` and a local 15-minute rollback timer.
Atlas was the pilot, followed by Prometheus and PBS. All timers were cancelled after validation.
For recovery, use the verified console and the saved `rollback-ssh.sh`. It removes only the new drop-in, validates SSH, and reloads the daemon.
The original configuration archive remains available for review. Do not replace host keys without a separately reviewed recovery procedure.

### Authentication, tokens, certificates, and time

PVE local administrator `root@pam` had no registered MFA methods. PBS had no local TFA configuration.
Normal `wbreiler@pid` access uses Pocket ID, and the user confirmed a passkey.
The PVE `hladmin` group has Administrator access. PBS grants `wbreiler@pid` Admin access.
The user confirmed local root MFA is not enrolled and reported enrollment/recovery options unavailable with default OpenID login.
A live check confirmed Pocket ID is the default realm, PVE has no TFA entries, and PBS has no local TFA file.
Local root enrollment and recovery codes remain pending. Select Linux PAM and authenticate as root for the local enrollment workflow.
OpenID account MFA and recovery remain managed by Pocket ID.
Do not expose TOTP seeds, security-key registration data, recovery codes, or passwords in this task file.

PVE monitor and NexDeck tokens have privilege separation enabled and read-only ACLs.
PBS monitor and NexDeck tokens have Audit/DatastoreAudit scopes, with the dashboard also permitted system audit.
These tokens have no expiry. Rotation requires preserving their known consumers; no token was rotated.
PBS backup-nash and Kuma writer identities retain prune-capable namespace roles. Their retention changes belong to H4.
No account, token, group, or ACL was modified during this audit.

| Host | Certificate evidence | Time evidence |
| --- | --- | --- |
| Atlas | PVE cluster CA; valid until April 29, 2028; management IP in SAN | Chrony normal, offset below 1 ms at inspection |
| Prometheus | PVE cluster CA; valid until April 29, 2028; management IP in SAN | Chrony normal, offset below 1 ms at inspection |
| Mnemosyne | Self-signed; valid until August 20, 3025; DNS SAN includes mnemosyne.wbreiler.com; management IP absent | Chrony normal, offset below 1 ms at inspection |

TLS connections passed real chain and hostname verification using certificates obtained over verified SSH.
PVE tests used the cluster CA and the management IPs. PBS used its pinned certificate and the DNS name with an explicit address override.
No certificate checks were disabled in these verification probes.
The existing PBS SHA-256 fingerprint matches the PVE storage configuration.
All three certificate hostnames failed normal resolution from this controller. The DNS override proves TLS, not production DNS availability.
Neither platform has an ACME account or DNS plugin configured. The standalone plugin is the only current plugin.
The certificate policy question offers native DNS-validated ACME or explicit private trust/pinning.
ACME requires working hostname access and a scoped DNS credential. PBS certificate replacement also requires updating the PVE storage fingerprint and validating backups.
No certificate, DNS record, credential, or trust store was changed.

### Packages and kernel maintenance

APT metadata refreshed successfully on all three hosts. Protected logs contain no index warnings or errors.
Upgrade simulation reported zero upgrades, additions, removals, or held upgrades on every host.
The installed default-kernel metapackage matches its current repository candidate. No package installation or kernel removal occurred.
Previous kernels remain available for recovery.

| Host | Running kernel | Installed target | Required maintenance |
| --- | --- | --- | --- |
| Atlas | 7.0.14-20-pve | 7.0.14-20-pve | No kernel reboot needed |
| Prometheus | 7.0.14-20-pve | 7.0.14-20-pve | Reboot and validation complete |
| Mnemosyne | 7.0.14-20-pve | 7.0.14-20-pve | Separate reboot and validation complete |

Both Prometheus and PBS EFI copies include the target and fallback kernels, with no manually selected kernel.
Pools are ONLINE, no failed systemd units appeared, and HA remains armed and quorate.
At the preflight placement check, Prometheus had 22 running containers. Placement changes automatically under HA load balancing.
Atlas had the five Minecraft guests, Vaultwarden, and NexDeck. These counts are a snapshot, not a migration instruction.
CTs 130 and 131 lack HA entries. Both use local-zfs and have peer replication; they need explicit migration handling.
Atlas has capacity for all running guest allocations and substantial free space in every applicable pool.
A fresh guest constraint, replication, capacity, task, and boot preflight remains required before shutdown.

The user authorized immediate execution after safety checks. The executed sequence was:

1. Wait for active backups/replication to finish and capture current guest placement and a fresh configuration backup.
2. Evacuate Prometheus through HA maintenance. Migrate non-HA CTs 130/131 explicitly. Validate applications, NFS, and the Tailscale router on Atlas.
3. After Prometheus has no running guests, disarm HA in freeze mode and verify watchdog release. Reboot Prometheus only.
4. Verify the target kernel, quorum, pools, firewall, key-only SSH, and guest health. Re-arm HA, then remove maintenance and restore reviewed placement.
5. In a separate idle PBS window, reboot Mnemosyne. Verify its target kernel, datastore, firewall, key-only SSH, API fingerprint, and PVE backup access.

Evacuation restarts LXCs and briefly interrupts their services, including Pocket ID and the Tailscale router.
The five Minecraft guests can remain on Atlas. Do not change their automatic balancing policy or start VM 122.
Budget 20–40 minutes for Prometheus evacuation/reboot/validation and 5–15 minutes for PBS, excluding a wait for active jobs.

### Authorized maintenance results

Prometheus rebooted at approximately 13:21 CDT and returned by 13:25 CDT.
PBS rebooted at approximately 13:30 CDT and returned by 13:32 CDT.
Both now run `7.0.14-20-pve`. Their boot IDs changed. Atlas remained running throughout both reboots.

- [x] Wait for all five hourly Minecraft backups to finish. Capture protected fresh host configurations, boot IDs, placement, and guest service/NFS baselines.
- [x] Evacuate Prometheus. Explicitly migrate non-HA CTs 130/131. Verify all 29 running guests on Atlas before shutdown.
- [x] Disarm HA in freeze mode. Verify the CRM and surviving Atlas watchdogs released. Keep expected votes at two during the temporary quorum loss.
- [x] Restore quorum and re-arm HA. Verify both LRM watchdogs active. Remove Prometheus maintenance and restore non-HA guests.
- [x] Reboot idle PBS separately. Verify the datastore, services, firewall, key-only SSH, unchanged certificate fingerprint, verified TLS, and PVE backup catalog access.

Final placement follows existing HA policies: 21 running containers on Prometheus and eight on Atlas.
All five Minecraft containers remain on Atlas with their balancing policy unchanged. VM 122 remains stopped.
All 29 guest service and NFS baselines passed after recovery. Tailscale reports Running and online.
All five Minecraft game status probes passed. All 30 replication jobs reported zero failures after maintenance.
Verified TLS passed on all three hosts after maintenance. An untrusted guest could not reach any host management API.
PVE read 785 PBS backup snapshots after the PBS reboot. This verifies catalog access, not a new backup or restore.

Deluge and SABnzbd had NFS startup timeouts after migration. Retrying their existing mount units restored the mounts and services.
SearXNG stalled during network shutdown on its return migration. An HA-managed stop/start and relocation restored its application on Prometheus.
No persistent guest configuration changed. The two existing failed Minecraft update units on CTs 115/116 remain deferred to guest maintenance.
The earlier NPM certbot failure cleared after restart. This does not establish that certificate renewal is repaired.

Protected local evidence is in ignored `truenas/artifacts/h3-maintenance-20261004/`.
The recovery archives contain sensitive host configuration. They are not committed.
H3 remains incomplete until local administrator MFA and the certificate policy are resolved.

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
