# Proxmox Cluster Ansible Automation

This Ansible project automates the setup of a Proxmox VE cluster with PBS backup integration, LXC container management, and system updates. Targets PVE 9 / Debian trixie.

**Cluster**: prometheus (10.10.30.3), atlas (10.10.30.9)
**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)
**Second play**: `site.yml` also applies network tuning to both proxmox_cluster and pbs_nodes groups

## Provisioning ownership

Terraform owns all existing guest hardware and lifecycle declarations. See
[the Terraform workflow](../terraform/README.md). Ansible configures software
inside existing, running guests and manages the PVE/PBS hosts.

The shared `tasks/create_lxc.yml` filename remains for caller compatibility,
but it never creates or starts containers. Missing or stopped guests fail
before application configuration. The VM deployment role and `macos.yml`
refuse provisioning requests. TUN passthrough must already exist before the
Tailscale application role runs.

Terraform also owns backup jobs, HA resources/rules, the PBS storage connection,
and cached images/templates. The old Ansible owners are removed from site.yml
and refuse direct execution. The HA service still controls runtime placement
and power. IP tagging remains with its existing service.

See [the historical repository audit](../LIVE_AUDIT.md) for the earlier baseline.
Current placement must be checked live rather than inferred from role defaults.

## Features

- **Repository Configuration**: Disables enterprise repositories (`.sources` format for PVE 9+) and configures the APT caching proxy
- **Cluster Setup**: Creates or joins a cluster only when `setup_cluster: true`
- **PBS Storage Connection**: Owned by Terraform, including its existing namespace. Ansible never removes and re-adds it.
- **ISO Management**: Owned by Terraform. Existing ISO and custom boot files are preserved.
- **LXC Templates**: Owned by Terraform with versioned sources and checksum pins.
- **Managed App LXCs**: Configures existing Apt-Cacher NG, Prowlarr, Homebridge, Spoolman, Bambuddy, Gitea Mirror, Seerr, Pocket ID, Forgejo, Sonarr, Radarr, Gatus, Diun, and a Tailscale subnet router through repository-owned roles
- **Backup Jobs**: Owned by Terraform. Existing schedules, selection, and retention remain unchanged.
- **VM Provisioning**: Owned by Terraform. The retired `vm_deploy` role fails explicitly.
- **macOS Tahoe**: VM 108 and its dedicated backup job are retired. [Installation notes](docs/macos.md) remain historical reference.
- **Network Tuning**: Configures storage VLAN subinterface and 10G TCP sysctl tuning (BBR, large buffers)
- **IP Tagging**: Tags LXC containers with their IP addresses in the Proxmox UI via a systemd service
- **Storage Cleanup**: Detects and optionally cleans up stale ZFS orphaned datasets from failed HA migrations
- **System Updates**: Updates Proxmox hosts and LXC operating-system packages without executing application-specific updater hooks
- **PBS Restore**: Restores LXC containers from Proxmox Backup Server backups with flexible targeting options

## Prerequisites

1. **Controller dependencies** installed on your control machine:

   ```bash
   python3 -m pip install -r requirements.txt
   ansible-galaxy collection install -r requirements.yml
   ```

2. **SSH access** to all Proxmox nodes through the configured SSH agent and user SSH configuration (`~/.ssh/cluster.pub` selects the agent-held key on the current controller)

3. **PBS server** configured and accessible

## Directory Structure

```console
proxmox-ansible/
├── ansible.cfg              # Ansible configuration
├── inventory.yml            # Proxmox nodes inventory (gitignored)
├── inventory.yml.example    # Example inventory
├── site.yml                 # Main playbook
├── requirements.txt         # Tested ansible-core and Python dependencies
├── requirements.yml         # Ansible Galaxy collection requirements
├── group_vars/
│   ├── proxmox_cluster.yml.example  # Example configuration
│   └── proxmox_cluster.yml          # Cluster-wide variables (gitignored, vault-encrypted)
├── host_vars/               # Per-host variables (corosync ring1 and legacy reference)
│   ├── node.yml.example     # Example host configuration
│   ├── prometheus.yml       # (gitignored)
│   └── atlas.yml            # (gitignored)
├── tasks/
│   ├── create_lxc.yml       # Existing LXC software bootstrap (legacy filename)
│   └── resolve_lxc_node.yml # Resolve the current node for an existing LXC
├── roles/
│   ├── configure_repos/     # Repository configuration role
│   ├── cluster_setup/       # Proxmox cluster creation role
│   ├── pbs_storage/         # Retired guard; Terraform owns the PBS connection
│   ├── pbs_backup_job/      # Retired guard; Terraform owns backup jobs
│   ├── manage_isos/         # Retired guard; Terraform owns cached media
│   ├── iptag/               # LXC IP tagging systemd service
│   ├── download_templates/  # Retired guard; Terraform owns pinned templates
│   ├── apt_cacher_ng/       # Managed Apt-Cacher NG LXC
│   ├── prowlarr/            # Managed Prowlarr LXC
│   ├── homebridge/          # Managed Homebridge LXC
│   ├── spoolman/            # Managed Spoolman LXC
│   ├── bambuddy/            # Managed Bambuddy LXC
│   ├── gitea_mirror/        # Managed Gitea Mirror LXC
│   ├── seerr/               # Managed Seerr LXC
│   ├── pocket_id/           # Managed Pocket ID LXC
│   ├── vaultwarden/         # Managed Vaultwarden password-manager LXC
│   ├── forgejo/             # Managed Forgejo LXC
│   ├── sonarr/              # Managed Sonarr LXC
│   ├── radarr/              # Managed Radarr LXC
│   ├── gallery_dl/          # retired reference role; not in site.yml
│   ├── gatus/               # Managed Gatus LXC (uptime monitoring/status page)
│   ├── diun/                # Managed Diun LXC (Docker image update watcher)
│   ├── tailscale_router/    # Managed Tailscale subnet router LXC
│   ├── update_all/          # System updates role (nodes + LXCs)
│   ├── lxc_auto_update/     # Guarded nightly Debian LXC package updates
│   ├── lxc_app_updates/     # Guarded weekly stable application updates
│   ├── update_reminder/     # Per-node Discord update reminders
│   ├── healthcheck_reminder/# Cluster-wide Discord down-node/guest alerts
│   ├── cleanup_storage/     # Stale ZFS dataset cleanup
│   ├── pbs_restore/         # PBS backup restore role
│   ├── vm_deploy/           # Retired VM deployment entry point
│   └── network_tuning/      # Storage VLAN + 10G TCP tuning
└── tests/                   # Local validation playbooks and fixtures
```

## Quick Start

### 1. Configure Inventory

Copy the example inventory, then update it with your Proxmox node details:

```bash
cp inventory.yml.example inventory.yml
```

```yaml
prometheus:
  ansible_host: 10.10.30.3
  proxmox_node_name: prometheus
atlas:
  ansible_host: 10.10.30.9
  proxmox_node_name: atlas
```

The tracked example also defines the `pbs_nodes` group and per-node network
tuning. Review those settings before running the second play. Legacy
`vmid_range_start`/`vmid_range_end` fields no longer allocate guests. Terraform
selects VMIDs. The abbreviated host list above is not a complete inventory.

### 2. Install Ansible Collections

Install required Ansible collections:

```bash
ansible-galaxy collection install -r requirements.yml
```

### 3. Configure Variables

Copy the example configuration file and customize it:

```bash
cp group_vars/proxmox_cluster.yml.example group_vars/proxmox_cluster.yml
```

Edit `group_vars/proxmox_cluster.yml` and update:

- **Cluster settings**:
  - Set `setup_cluster: true` to enable cluster creation
  - Set `cluster_name` to your desired cluster name
  - Set `cluster_master_node` to the first node
- **Application configuration**: Enable only the roles needed for existing guests.
- **Monitoring and maintenance**: Review service endpoints, update gates, and secrets.
- **Network tuning**: Review PVE and PBS interfaces before a full playbook run.

Configure the PBS connection, backup jobs, and media in Terraform. Historical
Ansible fields for those resources no longer configure them.

See [group_vars/proxmox_cluster.yml.example](group_vars/proxmox_cluster.yml.example) for all available options and detailed comments.

### 4. Secure Sensitive Data (Recommended)

Encrypt your variables file with Ansible Vault:

```bash
ansible-vault encrypt group_vars/proxmox_cluster.yml
```

You'll be prompted to create a vault password. To edit later:

```bash
ansible-vault edit group_vars/proxmox_cluster.yml
```

### 5. Test Connection

Verify Ansible can connect to all nodes:

```bash
ansible all -m ping
```

### 6. Run the Playbook

Execute the full setup:

```bash
# Without vault encryption
ansible-playbook site.yml

# With vault encryption
ansible-playbook site.yml --ask-vault-pass
```

## Running Specific Tasks

Use tags to run only specific parts of the playbook:

```bash
# Only configure repositories
ansible-playbook site.yml --tags repos

# Explicit cluster setup
ansible-playbook site.yml --tags cluster -e setup_cluster=true

# Only run system updates
ansible-playbook site.yml --tags update -e 'run_updates=true'

# Only restore from PBS backups
ansible-playbook site.yml --tags restore -e 'restore_from_pbs=true'

# Run multiple tags
ansible-playbook site.yml --tags "repos,iptag"
```

## Running on Specific Nodes

Target specific nodes using the `--limit` flag:

```bash
# Run only on atlas
ansible-playbook site.yml --limit atlas

# Run on multiple nodes
ansible-playbook site.yml --limit "atlas,prometheus"
```

## Configuration Details

### PBS connection, backup jobs, and images

These definitions now live in [Terraform](../terraform/README.md). Import
existing settings before any change. The PBS connection's current namespace,
certificate fingerprint, credentials, and retention defaults are preserved.
The four legacy roles (`pbs_storage`, `pbs_backup_job`, `manage_isos`, and
`download_templates`) are not invoked by `site.yml`. Direct invocation fails.
Their old enable flags and configuration examples are historical reference.

Terraform tracks existing ISO/boot files without replacing them. Cached LXC
source URLs and hashes are pinned. There is no automatic latest-template
selection, bulk pruning, network-share mount, or download cancellation job.
New images require a reviewed source and checksum. Unknown ISO sources and
custom boot media require an operator-supplied recovery source or backup.

### Cluster Setup

The playbook will automatically create a Proxmox cluster if `setup_cluster: true` in your variables file.

**How it works:**

1. The master node (defined by `cluster_master_node`) creates the cluster
2. All other nodes join the cluster
3. The cluster uses the node IPs defined in `inventory.yml`

**Important Notes:**

- All nodes must be able to communicate with each other on their management IPs
- Ensure nodes don't already belong to a cluster (the playbook checks this)
- Joins use `cluster_password` through an Ansible `expect` task when that
  variable is set; otherwise the role runs `pvecm add` without supplying a
  password and expects authentication to be available already
- After cluster creation, you can manage VMs across all nodes from the web UI

**To disable cluster setup:**
Set `setup_cluster: false` in `group_vars/proxmox_cluster.yml`

**To verify cluster status after setup:**

```bash
# On any node
pvecm status
pvecm nodes
```

### Monitoring

Four opt-in roles cover complementary monitoring concerns:

- **`healthcheck_reminder`** (`healthcheck_reminder_enabled: true`) — no new service. Installs a systemd timer on the cluster master node only (checks are cluster-wide via `pvesh get /cluster/resources`, so running it on both nodes would duplicate alerts). Every 5 minutes by default, it flags any Proxmox node that isn't `online` and any LXC/VM that isn't `running` (skip intentionally-stopped guests via `healthcheck_reminder_skip_vmids`), and sends a Discord alert. Re-notifies immediately if the set of down items changes, otherwise backs off for `healthcheck_reminder_repeat_after_minutes` (default 30) so an ongoing outage doesn't spam.
- **`gatus`** (`install_gatus: true`) — app-level checks and a status page/history that the script above can't give you. Configures existing `gatus-nash`, a small LXC running [Gatus](https://github.com/TwiN/gatus). The role builds it from a pinned, checksum-verified source tarball using a pinned, checksum-verified Go toolchain. The generated `config.yaml` probes each Proxmox node's web UI (TCP 8006), the PBS server (TCP 8007), and each enabled managed app role that defines a health URL. Add other checks through `gatus_extra_endpoints`.
- **`diun`** (`install_diun: true`) — watches configured container images for new tags or digests and sends a Discord alert. Configures existing `diun-nash`, a small LXC running [Diun](https://github.com/crazy-max/diun) from a pinned, checksum-verified release binary. It uses Diun's static `file` provider and the explicit `diun_watch_images` list, so it does not need Docker/API access to a target host. Checks every 6 hours by default (`diun_schedule`). `diun_first_check_notif: true` reports an image on its first scan; set `max_tags` on `watch_repo: true` entries to bound tag-history notifications.
  The dedicated LXC disables IPv6 by default (`diun_disable_ipv6: true`)
  because VLAN 40 provides IPv4 internet access but no routed IPv6; this keeps
  registry lookups from selecting unreachable AAAA records.
- **`centralized_logging`** (`install_centralized_logging: true`) — configures
  the existing `loki-nash` guest with Loki and Grafana. It installs Alloy on
  eligible running LXCs and both PVE hosts. Loki keeps logs for 30 days. Grafana includes one
  dashboard for service logs, host journals, and error counts.

Together: `healthcheck_reminder` catches "is the node/guest even up" (Proxmox-native, zero footprint); `gatus` catches "is the app inside actually responding" plus gives you history and a dashboard; `diun` catches "is there a newer image available" for anything running Docker, cluster or not.

### Apt-Cacher NG on Terraform-created guests

Set `app` to `apt_cacher_ng` in the [guest workflow](../terraform/README.md#create-a-guest-and-install-its-application)
profile. The workflow creates a Debian LXC or Debian/Ubuntu UEFI/Secure Boot VM
and invokes `apt-cacher-ng-guests.yml` with only that guest in its inventory.
The role installs Apt-Cacher NG from signed OS repositories, applies the existing
port and CONNECT settings, configures the guest's own APT proxy, enables the
service, and checks its report page. It leaves other APT clients unchanged.
The node-based role remains the default through `apt_cacher_ng_guest_ssh: false`.

For an existing Terraform-owned guest, copy the sanitized
`apt-cacher-ng-guests.inventory.yml.example` to a private inventory and run
from `proxmox/`:

```sh
ansible-playbook -i ../terraform/proxmox/artifacts/cache.inventory.yml apt-cacher-ng-guests.yml
ansible-playbook -i ../terraform/proxmox/artifacts/cache.inventory.yml apt-cacher-ng-guests.yml --check --diff
```

`tests/apt-cacher-ng-guests.yml` validates disposable Debian 13 guests. It checks
APT's signed metadata update through the configured cache, repeated proxy
requests, matching on-disk cached content, and an enabled, active service.

### Gatus on Terraform-created guests

For provisioning plus application configuration in one command, use the
[Terraform guest workflow](../terraform/README.md#create-a-guest-and-install-its-application).
The playbook waits for SSH and verifies a supplied Terraform hostname before
application changes. Its existing direct inventory entry point remains available.

`gatus-guests.yml` installs the existing Gatus application on Debian-family
AMD64 LXCs or VMs over SSH. Terraform must create and start the guests first.
Each guest needs Python 3, an authorized SSH key, and root access through SSH
or password-free sudo. The playbook selects `gatus_guest_ssh: true` and only
targets the `gatus_guests` inventory group. It contains no guest lifecycle or
hardware operations.

Use `gatus-guests.inventory.yml.example` as a sanitized inventory template.
Keep real addresses, identities, and host-key files in a protected inventory
outside Git. From `proxmox/`, review and deploy with:

```sh
ansible-playbook -i /path/to/private-inventory.yml gatus-guests.yml --check --diff
ansible-playbook -i /path/to/private-inventory.yml gatus-guests.yml
```

The SSH path reuses the role's pinned Gatus source, checksum-verified Go
toolchain, configuration template, systemd unit, and HTTP health check. Build
files, module cache, and Go scratch files use a private directory in `/var/tmp`.
Debian 13's RAM-backed `/tmp` cannot hold this source build. Compilation uses
bounded parallelism, and the build directory is removed after success or failure.

`gatus_extra_endpoints` provides explicit checks when the inventory has no
Proxmox or PBS groups. An empty `gatus_discord_webhook_url` disables notifications.
The existing node/pct workflow remains the default for `site.yml`; its task body
is preserved in `roles/gatus/tasks/lxc.yml`.

Live validation on 2026-10-26 deployed Gatus 5.36.0 to an unprivileged Debian
LXC and a Debian VM with UEFI and Secure Boot. Both dashboards, HTTP health
checks, and mutual peer checks passed. Both services started after a
Terraform-managed restart. A repeat Ansible run reported zero changes on both
guests, and the VM retained active Secure Boot and kernel lockdown.

### Standalone App LXCs

Repository-owned roles in this section manage single-purpose LXCs; the Tailscale router is documented separately below. Each is opt-in and defaults off. All bootstrap through the shared `tasks/create_lxc.yml` and adopt existing containers by hostname. Because adopted containers can be HA-managed and move between nodes, each role resolves the node currently hosting its container at run time (`tasks/resolve_lxc_node.yml`); the configured `<role>_node` is only the lookup fallback. Names, VMIDs, sizes, nodes, and versions below are tracked defaults, not assertions about live state.

- **`apt_cacher_ng`** — Apt-Cacher NG package cache with HTTPS pass-through and self-proxy configuration. Its defaults identify `apt-nash`, VMID 106, `atlas` as the lookup fallback, and a 2 CPU/512 MB/25 GB container. It removes the legacy remote update hook.
- **`prowlarr`** — Prowlarr indexer manager. Its defaults identify `prowlarr-nash`, VMID 104, and `atlas` as the lookup fallback. It pins version 2.6.5.5623 and its release checksum, removes the remote update hook, and verifies the web interface.
- **`homebridge`** — HomeKit bridge. Its defaults identify `homebridge-nash`, VMID 105, and `prometheus` as the lookup fallback. It pins package version 2.0.20, checksum-verifies the Homebridge repository key, removes the remote update hook, and verifies Homebridge and Avahi. For discovery across an externally routed VLAN, see [Homebridge discovery](#homebridge-discovery).
- **`spoolman`** — 3D-printer spool inventory. Its defaults identify `spoolman-nash`, VMID 102, and `atlas` as the lookup fallback. It pins and verifies Spoolman 0.27.0 and uv 0.11.29, preserves the existing environment and SQLite data, removes the remote update hook, and verifies the API-reported version.
- **`bambuddy`** — Bambu Lab printer management. It configures an existing unprivileged Debian LXC, installs a pinned and checksum-verified Bambuddy release using the sizing recommended by the Community Scripts installer, preserves local environment and data files, and verifies the web interface on port 8000. The pinned `nils_ost.bambuddy` collection is also installed for future API-driven printer and settings management; its Docker installer is not used.
- **`nexdeck`** — Infrastructure dashboard. The tracked release is 0.41.4; the
  role resolves existing placement and serves port 8000.
- **`homelable`** — Topology UI and discovery. See [Homelable](#homelable).
- **`speedtest_tracker`** — Scheduled Internet speed checks. See [Speedtest Tracker](#speedtest-tracker).
- **`gitea_mirror`** — Gitea Mirror repository mirroring service. Its defaults identify `git-mirror-nash`, VMID 119, and `atlas` as the lookup fallback. It pins and verifies Gitea Mirror 3.41.0 and Bun 1.3.14, preserves the existing environment file and SQLite data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the installed version.
- **`seerr`** — Seerr media-request manager. Its defaults identify `seerr-nash`, VMID 117, and `atlas` as the lookup fallback. It pins and verifies Seerr 3.5.0 and pnpm 10.34.4, requires Node.js 22, preserves `/etc/seerr/seerr.conf` and the SQLite config data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the API-reported version.
- **`pocket_id`** — Pocket ID OIDC identity provider. Its defaults identify `pocketid-nash`, VMID 100, and `atlas` as the lookup fallback. It pins and verifies the Pocket ID 2.18.0 binary, preserves the `.env` and SQLite data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`vaultwarden`** — Vaultwarden password manager. Its defaults identify `vaultwarden-nash`, VMID 125, and `atlas` as the lookup fallback. Based on the Community Scripts design without executing its installer, it builds pinned Vaultwarden 1.37.4 source with pinned Rust 1.97.1, installs the pinned matching web vault, preserves and verifies SQLite data, uses a hardened non-root systemd service, and rolls back failed upgrades.
- **`forgejo`** — Forgejo Git hosting. Its defaults identify `forgejo-nash`, VMID 103, and `prometheus` as the lookup fallback. It pins and verifies the Forgejo 16.0.6 release binary, refuses downgrades and skipped major versions, preserves `app.ini` and repository data, checks SQLite integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`sonarr`** — Sonarr TV manager. Its defaults identify `sonarr-nash`, VMID 110, and `atlas` as the lookup fallback. It pins and verifies Sonarr 4.0.20.3014, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`radarr`** — Radarr movie manager. Its defaults identify `radarr-nash`, VMID 111, and `prometheus` as the lookup fallback. It pins and verifies Radarr 6.4.4.10685, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`gallery_dl` (retired 2026-10-24)** — retained as reference code only.
  `site.yml` no longer imports this role. Its enable flag and profiles were
  removed from the local active variables and the tracked configuration example.
  Ordinary site runs and the old tag/enable flag cannot recreate the retired LXC.
  Existing data, backups, and the ignored cookies file were not deleted.
- **`gatus`** — Uptime monitoring/status page. See [Monitoring](#monitoring) above for details.
- **`diun`** — Docker image update watcher. See [Monitoring](#monitoring) above for details.
- **`centralized_logging`** — Loki, Grafana, and Alloy. See [Centralized logging](#centralized-logging).

### Sonarr and Radarr storage startup

The separate [arr storage playbook](docs/arr-storage.md) orders DHCP completion
before NFS mounts and requires all configured media/download mounts before
application startup. Native timers retry failed starts. Both LXCs passed
separate reboot, mount-order, HTTP, and media-user read/write tests on 2026-10-02.
Application roles preserve these systemd drop-ins but do not deploy them.

### Homepage dashboard

The [NexDeck homepage](files/nexdeck/README.md) provides a Live page with media
artwork, activity tabs, and homelab status. Its Bookmarks page keeps categorized
service links and everyday favorites. The editable Start board preserves the
separate Home monitoring board.

### Centralized logging

The role pins logging packages to exact versions and holds them with APT.
Normal OS upgrades therefore skip Alloy. Update the version defaults for a
controlled upgrade. The role permits that explicit upgrade and retains the hold.

Grafana is available at `http://10.10.40.193:3000` over the LAN/Tailscale
subnet route. Local DNS now resolves the internal NPM name `http://graf-nash`.
The [local services configuration](docs/local-services.md) also provides its
private HTTPS route. Clients must use the UniFi resolver for these names.
No public DNS record or port forward is required or created.

The role manages `/etc/nginx/conf.d/homelab-grafana.conf` inside NPM. This
route permits only private/Tailscale source addresses, using the actual
connection peer instead of client-supplied headers. It is separate from
NPM's UI-managed proxy entries. The role checks Nginx configuration before
reload and restores the previous file if validation fails.

The role stores Loki data in `/var/lib/loki` inside `loki-nash`. It provisions
the Loki data source and the **Homelab Logs** dashboard in Grafana. Retrieve the
generated Grafana password without printing it into Ansible logs:

```bash
ssh root@10.10.30.3 'pct exec 127 -- cat /etc/grafana/admin-password'
```

Loki HTTP listens only on `127.0.0.1:3101`. Its gRPC listener also uses
loopback. Grafana queries that local HTTP listener. A dedicated Nginx
configuration exposes port `3100` for `POST /loki/api/v1/push` and
`GET /ready`. It rejects every other path and method. It does not start
the Nginx default website or change other firewall rules.

Before enabling the role, set `centralized_logging_ingest_cidrs` in the
ignored local group variables. The default is empty and fails validation.
List each collector's actual IPv4 source as a `/32`. Include both Proxmox
hosts for collection and readiness checks. For example:

```yaml
centralized_logging_ingest_cidrs:
  - "192.0.2.10/32"  # Replace with the first Proxmox source.
  - "192.0.2.11/32"  # Replace with the second Proxmox source.
  - "192.0.2.20/32"  # Replace with a guest collector source.
```

Use each host's route to the logging guest to confirm its source address.
The role automatically permits loopback and the logging guest's own address.
Update the list before deploying Alloy to a new guest or changing DHCP
addresses. This list remains an explicit policy. Discovery does not expand it.

This ingress prevents remote log queries. It does not authenticate ingestion.
An allowed host can submit forged log records. SNAT also shares its allowed
source identity with forwarded clients. This includes Tailscale clients when
the allowed subnet router applies SNAT. Those clients still cannot query logs
through port `3100`.

Run the role again after a new LXC starts. The role discovers each running LXC
and installs Alloy. Add an application log path in
`roles/centralized_logging/templates/alloy.config.j2` and its read-access
directory in `tasks/deploy_lxc_agent.yml`. Forgejo logs arrive through its
systemd journal. NPM and the *arr hosts also ship application files.

Change `centralized_logging_retention` to change the Loki retention period.
The minimum supported period is 24 hours. The compactor checks every ten
minutes and deletes expired chunks after a two-hour delay. An isolated test
verified deletion of synthetic 31-day-old chunks with the same 720-hour
retention. Production logs have not yet reached 30 days.

Two Grafana rules show missing Proxmox logs and an NPM error spike. No
external notification channel is configured. Gatus and the cluster health
reminder provide separate checks. The former Uptime Kuma deployment is retired.

Game servers start in `centralized_logging_excluded_vmids`. Remove one VMID at
a time after the 30-day storage rate is known. The main PBS job includes VMID
127 because that job backs up all non-game guests. Its root disk contains
all Loki data, Grafana data, and configuration. Diun (121) is also excluded
until its 256 MiB RAM allocation can be increased safely. The router's Alloy
package is installed. Guest 123 now has 512 MiB RAM after the 2026-10-02
update exposed an out-of-memory failure at 256 MiB.

The addresses above are the deployment snapshot. Reserve the DHCP leases
in the existing DHCP server to keep them stable. If an address changes,
rerun the role and update client hosts-file entries as needed.

For a delivery check, emit the same unique marker with `logger -t
homelab-logging-check MARKER` on each included host. Then run
the verification script inside `loki-nash` through SSH:

```bash
python3 /root/verify_logging.py http://127.0.0.1:3101 MARKER HOST...
```

Copy `roles/centralized_logging/files/verify_logging.py` there first. The check
requires every expected host and rejects labels outside `host`, `job`, and
`unit`. Direct network queries through port `3100` are refused.

For an isolated retention check, copy
`roles/centralized_logging/files/verify_retention.py` into `loki-nash` and
run it with Python 3 as root. It uses local-only test ports and separate
temporary storage, then stops its test process.

Deployment checks on 2026-09-14 confirmed 21 sources, persistent journals,
Grafana authentication, datasource health, and dashboard provisioning.
The three pilot journals and both application-file sources delivered test
markers within 12.8 seconds. The isolated 30-day retention test deleted its
expired synthetic chunk. Five game servers and Diun remain excluded.

```bash
ansible-playbook -i inventory.yml site.yml --tags centralized_logging \
  -e install_centralized_logging=true
```

```yaml
install_apt_cacher_ng: true
apt_cacher_ng_node: "atlas"
apt_cacher_ng_vmid: "106"
apt_cacher_ng_hostname: "apt-nash"
apt_cacher_ng_vlan: 40

install_prowlarr: true
prowlarr_node: "atlas"
prowlarr_vmid: "104"
prowlarr_version: "2.6.5.5623"

install_homebridge: true
homebridge_node: "prometheus"
homebridge_vmid: "105"
homebridge_version: "2.0.20"

install_spoolman: true
spoolman_node: "atlas"
spoolman_vmid: "102"
spoolman_version: "0.27.0"

install_bambuddy: true
bambuddy_node: "atlas"
bambuddy_vmid: ""  # legacy field; bootstrap resolves the existing guest by hostname
bambuddy_version: "1.2.5.7"

install_gitea_mirror: true
gitea_mirror_node: "atlas"  # lookup fallback; the role finds the current host itself
gitea_mirror_vmid: "119"
gitea_mirror_version: "3.41.0"

install_seerr: true
seerr_node: "atlas"  # lookup fallback; the role finds the current host itself
seerr_vmid: "117"
seerr_version: "3.5.0"

install_pocket_id: true
pocket_id_node: "atlas"
pocket_id_vmid: "100"
pocket_id_version: "2.18.0"

install_vaultwarden: true
vaultwarden_node: "atlas"
vaultwarden_vmid: "125"
vaultwarden_domain: "https://vault.wbreiler.com"
# Temporarily enable signups for initial account creation, then disable them.

install_forgejo: true
forgejo_node: "prometheus"
forgejo_vmid: "103"
forgejo_version: "16.0.6"  # never skip a major; upgrade one major at a time

install_sonarr: true
sonarr_node: "atlas"
sonarr_vmid: "110"
sonarr_version: "4.0.20.3014"

install_radarr: true
radarr_node: "prometheus"
radarr_vmid: "111"
radarr_version: "6.4.4.10685"

install_gatus: true
gatus_node: "atlas"
gatus_vmid: ""  # legacy field; bootstrap resolves the existing guest by hostname
gatus_version: "5.36.0"
gatus_discord_webhook_url: ""  # set in vault-encrypted group_vars

install_diun: true
diun_node: "atlas"
diun_vmid: ""  # legacy field; bootstrap resolves the existing guest by hostname
diun_version: "4.33.0"
diun_discord_webhook_url: ""  # set in vault-encrypted group_vars
diun_watch_images:
  - name: "example/app:1.2.3"
    watch_repo: true
    sort_tags: "semver"
    max_tags: 3  # cap tracked tag history — keeps re-baselines quiet

healthcheck_reminder_enabled: true
healthcheck_reminder_discord_webhook_url: ""  # set in vault-encrypted group_vars
```

```bash
ansible-playbook -i inventory.yml site.yml --tags apt_cacher_ng -e 'install_apt_cacher_ng=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags prowlarr -e 'install_prowlarr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags homebridge -e 'install_homebridge=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags spoolman -e 'install_spoolman=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags bambuddy -e 'install_bambuddy=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags gitea_mirror -e 'install_gitea_mirror=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags seerr -e 'install_seerr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags pocket_id -e 'install_pocket_id=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags forgejo -e 'install_forgejo=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags sonarr -e 'install_sonarr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags radarr -e 'install_radarr=true' --ask-vault-pass
ansible-playbook site.yml --tags gatus -e 'install_gatus=true' --ask-vault-pass
ansible-playbook site.yml --tags diun -e 'install_diun=true' --ask-vault-pass
ansible-playbook site.yml --tags tailscale_router -e 'install_tailscale_router=true' --ask-vault-pass
```

After deployment, point APT clients at `http://<container-ip>:3142`. The report page is available at `http://<container-ip>:3142/acng-report.html`.

### Tailscale Subnet Router

`tailscale_router` (`install_tailscale_router: true`) gives every device on your tailnet access to the whole homelab LAN without per-device WireGuard configs. It configures the existing unprivileged LXC (`tailscale-router-nash`), requires existing `/dev/net/tun` passthrough, enables IPv4/IPv6 forwarding, installs a pinned, checksum-verified-key `tailscale` package, and runs `tailscale up --advertise-routes=...` using a reusable auth key from the Tailscale admin console (`tailscale_router_auth_key`, vault-encrypted).

Set `tailscale_router_advertise_routes` to your LAN CIDR(s) (e.g. `["10.10.0.0/16"]`) — the role refuses to run without at least one. **New or changed routes still need one-time approval** in the Tailscale admin console (Machines → this device → Edit route settings), unless `autoApprovers` is configured in your tailnet ACL. Once approved, any device on the tailnet can reach the homelab subnet directly — no client-side routes or WireGuard peers to manage.

```yaml
install_tailscale_router: true
tailscale_router_auth_key: ""  # set in vault-encrypted group_vars
tailscale_router_advertise_routes:
  - "10.10.0.0/16"
```

```bash
ansible-playbook -i inventory.yml site.yml --tags tailscale_router -e 'install_tailscale_router=true' --ask-vault-pass
```

### System Updates

#### Automatic LXC OS updates

The `lxc_auto_update` role installs a systemd timer on each Proxmox node.
It runs nightly at 03:15 America/Chicago with up to 15 minutes of delay.
Each run discovers the node's running LXCs, including guests moved by HA.
The Mac and Codex do not need to be online.

```bash
ansible-playbook site.yml --tags lxc_auto_update \
  -e 'install_lxc_auto_update=true lxc_auto_update_enabled=true'
```

Set these flags in the ignored group variables to preserve the configuration.
The updater requires an LXC backup on `lxc_auto_update_backup_storage` from
the last eight hours. A missing, stale, or failed-verification backup blocks
that guest's update and fails the service. Existing Terraform backup jobs
remain responsible for backups. No backup schedules are changed.

APT updates preserve package holds, pins, and modified configuration files.
They permit new dependencies but forbid package removals. This updates apps
installed as eligible APT packages as well as OS packages. Source releases,
Docker images, and Minecraft modpacks require their separate update methods.
The job never updates host packages, executes `/usr/bin/update`, starts a
stopped guest, or reboots a guest. Package upgrades can restart services.
New failed systemd services fail the job. Missed windows do not run at boot.

```bash
# On each Proxmox node; simulation uses the existing package metadata.
lxc-auto-update --dry-run
systemctl list-timers lxc-auto-update.timer
journalctl -u lxc-auto-update.service
```

Use `lxc_auto_update_skip_vmids` to exclude guests. To disable the timer, rerun
the role with `install_lxc_auto_update=true lxc_auto_update_enabled=false`.

#### Automatic stable application updates

The opt-in `lxc_app_updates` role runs on both PVE nodes. Its weekly timer
starts Sunday at 01:15 America/Chicago, with up to 15 minutes of delay.
Codex and the controller can be offline. Missed windows do not run at boot.

```bash
ansible-playbook site.yml --tags lxc_app_updates -e install_lxc_app_updates=true
# On each node, inspect discovery before enabling the schedule:
/opt/homelab-app-updates/lxc_app_updates.py --dry-run
```

Set `install_lxc_app_updates: true` and `lxc_app_updates_enabled: true` in
ignored group variables after validation. Deploy the same tag again.
The role copies application settings into a root-only server configuration.
Redeploy this role after changing application settings in the inventory.

Stable releases must remain within the installed major version. For 0.x,
they must also remain within the installed minor version. GitHub and
Codeberg releases must be at least 72 hours old. Signed APT candidates must
remain the selected candidate for 72 hours after first discovery.
Prereleases, downgrades, and unrecognized version formats do not install.
The updater resolves exact artifact checksums and container digests before
deployment. It uses repository-owned URL templates and verifies downloads.

Every actual app update requires a new, successful PBS snapshot backup.
Existing Terraform backup schedules and retention remain unchanged.
The updater discovers only running local guests and shares the OS updater's
lock. It never changes guest power, guest hardware, or host packages.
Application updates can restart services and migrate application databases.
Version and health checks must pass before successful pins are saved.

Coverage includes Pocket ID, Spoolman, Forgejo, Prowlarr, Homebridge, Sonarr,
Radarr, Seerr, Gitea Mirror, Diun, Vaultwarden, Zipline, Bambuddy, NexDeck,
Speedtest Tracker, and Homelable. The signed package path covers Alloy,
Loki, Grafana, and Tailscale. Optional `lxc_app_updates_native_guests` mappings
enable Nginx Proxy Manager, SABnzbd, Open WebUI, LibreSpeed, and netboot.xyz.
For DHCP settings across VLANs, see [PXE network boot](docs/network-boot.md).
See the variable example and `roles/lxc_app_updates/files/catalog.yml`.

SearXNG publishes no stable releases and remains manual. Manual Minecraft
packs retain their existing workflow. Other Minecraft timers remain unchanged.
Auxiliary PostgreSQL/Apprise images and build tools retain their existing pins.
NPM's OpenResty/Certbot installation also remains separate from its app release.

```bash
systemctl list-timers lxc-app-updates.timer
journalctl -u lxc-app-updates.service
cat /var/lib/homelab-app-updates/last-run.json
# Optional immediate update of one application, with backup and health checks:
/opt/homelab-app-updates/lxc_app_updates.py diun
```

Successful pins and failed-deployment markers live in the cluster-private
`/etc/pve/priv/homelab-app-updates` directory. Later role runs adopt successful
pins, preventing unintended downgrades. Explicit Ansible extra vars override
these pins. Failed apps remain blocked until an operator inspects the journal
and runs the selected app with `--retry-failed`. PBS restore is manual.
If the failed update already installed the target version, repair and verify
the application before removing its specific `*.failed.json` marker.
Native adapters preserve old code and build before stopping services, but
do not automatically reverse database migrations. Retained releases and
artifact caches require occasional disk-space review.

Disable the schedule with `lxc_app_updates_enabled: false` and redeploy the
role. Use `lxc_app_updates_exclude` for individual catalog applications.

#### Discord maintenance notifications

Set `lxc_update_discord_webhook_url` in ignored group variables or Vault.
It can reference an existing webhook, such as `"{{ diun_discord_webhook_url }}"`.
An empty value disables notifications. Deploy the `lxc_auto_update` and
`lxc_app_updates` tags after changing this setting.

Both services send one result summary per node after each actual run,
including successful runs with no eligible updates. Summaries identify failed
guests, updated app versions, and updated signed packages. OS summaries count
completed guests rather than claiming a package changed on every guest.
Startup failures and missing reports also produce a failure notification.
Dry runs and direct updater CLI commands do not send messages.

Messages lead with the outcome, with the node and job above it. A single
summary line shows nonzero counts instead of separate metric columns.
App names, LXC names, and container IDs head each update entry, with
`old version → new version` below. Managed packages share one entry per
container, with both versions listed for each package. Reports save the
version read before the update and the verified installed version. Older
reports show `unknown` when the previous version was not recorded. Both update
jobs save the LXC name from Proxmox with each result. Entries show `name (CT ID)`, or
only `CT ID` for older reports and unknown guests. Failures appear first, with
a copyable journal command labeled for the correct node. Quiet runs stay
short. Long lists retain totals and show an overflow count with the log
command. `--test` clearly labels sample data while preserving the real layout
and status colors, including a simulated app failure, without running maintenance.

The systemd completion hook checks the current invocation ID so an old report
cannot hide a new failure. It sends only selected status fields, never logs,
exception details, or credentials. The webhook remains in a root-only file
and outside command arguments. Mentions are disabled, and Discord must confirm
message creation. Bounded delivery retries never repeat application updates.
Notification delivery failures fail the service and remain visible in its journal.
The webhook behavior follows the [Discord API documentation](https://docs.discord.com/developers/resources/webhook#execute-webhook).

```bash
# On each node: a labeled delivery test, without guest updates.
/usr/local/sbin/lxc-update-notify os --test
```

Reports live at `/var/lib/lxc-auto-update/last-run.json` and
`/var/lib/homelab-app-updates/last-run.json`. Each contains an `invocation_id`
and a `results` list. Application dry-run plans remain plain lists.

#### Manual system and application updates

Install the repository-owned Community Scripts application updater with:

```bash
ansible-playbook site.yml --tags update_apps -e 'install_update_apps=true' --ask-vault-pass
```

Run `update-apps --dry-run` on a Proxmox node to list eligible local LXCs. Run
`update-apps` to create a backup and invoke each existing in-container updater.
The command excludes LXCs managed by dedicated Ansible roles. It does not
download or source the upstream orchestration script.

The `update_all` role updates Proxmox hosts and operating-system packages in running LXC containers (apt for Debian/Ubuntu, apk for Alpine). It never executes application-specific updater hooks. Managed applications use explicit role pins or the guarded `lxc_app_updates` workflow.

After apt upgrades, it runs autoremove to remove unused packages and eligible
old kernels, then autoclean to remove obsolete package downloads. APT and
Proxmox kernel retention rules still apply.

**Usage:**

```bash
# Update all nodes and LXCs
ansible-playbook site.yml --tags update -e 'run_updates=true' --ask-vault-pass

# Update nodes only (skip LXCs)
ansible-playbook site.yml --tags update -e 'run_updates=true' -e 'update_lxcs=false' --ask-vault-pass

# Update LXCs only (skip nodes)
ansible-playbook site.yml --tags update -e 'run_updates=true' -e 'update_nodes=false' --ask-vault-pass

# Auto-reboot nodes if kernel was updated
ansible-playbook site.yml --tags update -e 'run_updates=true' -e 'update_reboot_if_required=true' --ask-vault-pass
```

**Skip specific containers** by VMID in `group_vars/proxmox_cluster.yml`:

```yaml
update_skip_vmids:
  - 100
  - 101
```

### Update Reminders

The `update_reminder` role installs a systemd timer on every Proxmox node. Each
node refreshes its package indexes, simulates an OS upgrade for itself and its
currently running LXCs, and sends its own Discord reminder when the configured
package threshold is met. It never installs updates.

The default timer checks daily with up to one hour of randomized delay. A node
notifies at most once every seven days while updates remain pending. Its
cooldown resets after a check finds fewer pending packages than the threshold.
Unsupported LXC package managers are skipped, and failed checks are recorded in
the system journal.

Store the webhook only in the Vault-encrypted
`group_vars/proxmox_cluster.yml`, not in the tracked example:

```yaml
update_reminder_enabled: true
update_reminder_discord_webhook_url: >-
  https://discord.com/api/webhooks/REPLACE_WITH_REAL_SECRET
update_reminder_schedule: "*-*-* 09:00:00"
update_reminder_randomized_delay: "1h"
update_reminder_package_threshold: 1
update_reminder_repeat_after_days: 7
update_reminder_include_lxcs: true
update_reminder_skip_vmids:
  - 100
```

Deploy or reconfigure only the reminder:

```bash
ansible-playbook -i inventory.yml site.yml \
  --tags update_reminder \
  --ask-vault-pass
```

Inspect the schedule and most recent check on a node:

```bash
systemctl list-timers homelab-update-reminder.timer
journalctl -u homelab-update-reminder.service
```

### Health Check Reminders

The `healthcheck_reminder` role installs a systemd timer on the cluster
master node only — checks are cluster-wide via `pvesh get /cluster/resources`,
so running it on both nodes would duplicate alerts. Every 5 minutes by
default it flags any Proxmox node that isn't `online` and any LXC/VM that
isn't `running`, then sends a Discord alert. It re-notifies immediately if the
set of down items changes, otherwise backs off for
`healthcheck_reminder_repeat_after_minutes` (default 30) so an ongoing
outage doesn't spam.

Store the webhook only in the Vault-encrypted
`group_vars/proxmox_cluster.yml`, not in the tracked example:

```yaml
healthcheck_reminder_enabled: true
healthcheck_reminder_discord_webhook_url: >-
  https://discord.com/api/webhooks/REPLACE_WITH_REAL_SECRET
healthcheck_reminder_schedule: "*:0/5"
healthcheck_reminder_randomized_delay: "10s"
healthcheck_reminder_repeat_after_minutes: 30
healthcheck_reminder_skip_vmids:
  - 100  # e.g. templates or guests intentionally kept stopped
```

Deploy or reconfigure only the reminder:

```bash
ansible-playbook -i inventory.yml site.yml \
  --tags healthcheck_reminder \
  --ask-vault-pass
```

Inspect the schedule and most recent check on the cluster master node:

```bash
systemctl list-timers homelab-healthcheck-reminder.timer
journalctl -u homelab-healthcheck-reminder.service
```

### PBS Restore

The `pbs_restore` role restores LXC or QEMU backups. It supports different target
VMIDs and storage, and optional startup after restore. Set `restore_from_pbs=true`
to enable it. Select an existing target storage; this cluster has no `local-lvm`.

**Usage:**

```bash
# Restore a specific container from latest backup
ansible-playbook site.yml --tags restore -e 'restore_from_pbs=true' \
  -e '{"pbs_restore_containers": [{"vmid": 100}]}' --ask-vault-pass

# Restore to a different VMID and start after restore
ansible-playbook site.yml --tags restore -e 'restore_from_pbs=true' \
  -e '{"pbs_restore_containers": [{"vmid": 100, "target_vmid": 200, "start_after_restore": true}]}' \
  --ask-vault-pass

# Force restore (overwrite existing container)
ansible-playbook site.yml --tags restore -e 'restore_from_pbs=true' \
  -e '{"pbs_restore_containers": [{"vmid": 100, "force": true}]}' --ask-vault-pass
```

**Configuration in `group_vars/proxmox_cluster.yml`:**

```yaml
restore_from_pbs: true
pbs_restore_node: "atlas"
pbs_restore_storage: "helios"
```

### IP Tagging

The `iptag` role installs a repository-owned Python systemd service that tags LXC containers and VMs with their IP addresses in the Proxmox UI. Enabled by default (`install_iptag: true`).

The role manages the runtime, configuration, `iptag-run` command, and systemd unit directly with Ansible. Existing installations are migrated from the legacy `/lib/systemd/system/iptag.service` unit to `/etc/systemd/system/iptag.service`.

```yaml
install_iptag: true
iptag_tag_format_choice: 2  # 1=last two octets, 2=last octet, 3=full
iptag_loop_interval: 300
iptag_allowed_cidrs:
  - 192.168.0.0/16
  - 10.0.0.0/8
  - 100.64.0.0/10
iptag_debug: false
iptag_command_timeout: 8
```

Run `iptag-run` on a Proxmox node for an immediate one-shot reconciliation. Configuration changes are validated before the service is started, and the previous configuration is backed up when Ansible replaces it.

### LXC Template Downloads

Terraform owns versioned template files. The Ansible download role is retired.
Use the pinned source/checksum workflow in [Terraform](../terraform/README.md).

### Storage Cleanup

The `cleanup_storage` role detects ZFS datasets left behind by failed HA migrations and optionally destroys them. Dry-run by default — set `cleanup_storage_destroy_stale: true` to actually remove orphaned volumes. Also reports LXC configs referencing datasets that don't exist on the current node.

```bash
# Dry-run (report only)
ansible-playbook site.yml --tags cleanup -e 'run_cleanup_storage=true'

# Destroy stale datasets
ansible-playbook site.yml --tags cleanup \
  -e 'run_cleanup_storage=true' -e 'cleanup_storage_destroy_stale=true'
```

### VM Deployment

Use [Terraform](../terraform/README.md) for new VMs and hardware changes. The
legacy `deploy_vms` flag now selects an explicit failure instead of guest
creation. Existing VM definitions and defaults remain historical input only.
`macos.yml` also refuses provisioning. Existing media and backups are preserved.

### Network Tuning

The `network_tuning` role runs on both Proxmox cluster nodes and PBS nodes. It configures a storage VLAN subinterface (`vmbr0.<vlan_id>` with a static IP) and applies 10G TCP sysctl tuning (BBR congestion control, 134MB buffer sizes).

Controlled by per-host variables in `inventory.yml`:

```yaml
network_tuning_configure_vlan: true
network_tuning_storage_vlan_ip: "10.10.20.5"
```

Run with `--tags network` to apply without the full playbook.

## Adding New Nodes

To add a new Proxmox node to your cluster:

### 1. Update Inventory

Add the new node to `inventory.yml`:

```yaml
newnode:
  ansible_host: 10.10.30.X
  proxmox_node_name: newnode
  network_tuning_configure_vlan: true
  network_tuning_storage_vlan_ip: "10.10.20.X"
```

The addresses above are placeholders. Review live allocation before assigning
them. Terraform owns guest IDs and hardware. Legacy Ansible VMID ranges do not
allocate guests.

### 2. Create Host Variables

Create `host_vars/newnode.yml` from the example:

```bash
cp host_vars/node.yml.example host_vars/newnode.yml
```

Set the node-specific corosync address. PBS connection credentials and namespace
are managed separately in Terraform:

```yaml
---
corosync_ring1_addr: "10.10.50.X" # node's IP on the corosync ring1 network
```

### 3. Run Playbook on New Node

Install everything on the new node:

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode
```

Or skip cluster setup:

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode --skip-tags cluster
```

### 4. Join to Cluster (Optional)

If you already have a cluster and want to add the new node:

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode --tags cluster -e setup_cluster=true
```

### 5. Verify

Check that the node is configured correctly:

```bash
# Verify Ansible can connect
ansible newnode -m ping

# Check cluster membership (if joining cluster)
ssh root@10.10.30.X pvecm nodes
```

## Adding New Roles

See [Contributing](#contributing) for the high-level workflow. Follow the pattern of existing roles for structure, `when`-gate variables, and tagging conventions.

## Troubleshooting

### SSH Connection Issues

If you get SSH connection errors:

```bash
# Test SSH using the user configuration and configured SSH agent
ssh root@10.10.30.9

# Inspect the effective SSH configuration without connecting
ssh -G root@10.10.30.9 | rg '^(hostname|user|identityfile|identityagent) '
```

### Repository Issues

If you see subscription warnings or repository errors:

```bash
# On a Proxmox node (PVE 9 uses .sources format)
cat /etc/apt/sources.list.d/pve-enterprise.sources   # should have Enabled: false
cat /etc/apt/sources.list.d/proxmox.sources          # should include pve-no-subscription
cat /etc/apt/sources.list.d/ceph.sources             # should have Enabled: false
apt update
```

### Cluster Issues

**Nodes won't join the cluster:**

```bash
# Check if node is already in a cluster
pvecm status

```

Removing a node from a cluster is destructive and is intentionally not
documented as a copy/paste troubleshooting step. Confirm backups, quorum,
guest placement, and the current Proxmox procedure before changing membership.

**Check cluster communication:**

```bash
# Verify nodes can reach each other (management network)
ping 10.10.30.3  # prometheus
ping 10.10.30.9  # atlas

# Check corosync status
systemctl status corosync
journalctl -u corosync -n 50
```

**Quorum issues:**

```bash
# Check quorum status
pvecm status

```

`pvecm expected <votes>` changes quorum state; do not use it as an inspection
command. The role only runs it when the opt-in `set_expected_votes` gate is
enabled.

### PBS Connection Issues

Verify PBS storage manually:

```bash
# On a Proxmox node
pvesm status
pvesm list mnemosyne
```

### ISO Download Issues

Check ISO storage:

```bash
# List ISOs
ls -lh /var/lib/vz/template/iso/
pvesm list local --content iso
```

## Testing

You can test roles locally without Proxmox nodes using the test playbooks in the `tests/` directory:

```bash
# Verify that retired platform roles refuse mutation
ansible-playbook -i localhost, tests/terraform-platform-ownership.yml
```

See [tests/README.md](tests/README.md) for more information.

## Advanced Usage

### Dry Run Mode

Check what would change without making changes:

```bash
ansible-playbook site.yml --check
```

### Verbose Output

Get detailed execution information:

```bash
ansible-playbook site.yml -v   # verbose
ansible-playbook site.yml -vv  # more verbose
ansible-playbook site.yml -vvv # very verbose (includes connection debugging)
```

### Parallel Execution

Control how many nodes run simultaneously:

```bash
ansible-playbook site.yml --forks 10
```

Use `mnemosyne` for the current cluster storage ID. Its PBS datastore is
`mneme`, namespace `cluster-nash`; these are different identifiers.

## Maintenance

### Nginx Proxy Manager certificate renewals

NPM certificate metadata and Certbot renewal files must agree. If an HTTP
challenge reaches another site or an unavailable origin through Cloudflare,
use DNS validation with a credential authorized for the certificate's zone.
Test against staging before production issuance. Include every hostname
served by the certificate; an apex certificate alone does not cover its
subdomains. Keep credentials out of command arguments and logs.

After changing validation methods, reconcile NPM's domains, expiry, DNS
provider, and credential metadata. Verify a renewal dry run using the saved
configuration and check the certificate actually served for each affected
SNI hostname. Validate Nginx before `nginx -s reload`; this installation's
OpenResty unit does not implement `systemctl reload`.

For an explicitly retired endpoint, preserve a backup, disable its NPM host
and certificate records, and archive its generated proxy and renewal files
outside their active directories. Retain the certificate lineage and keys
for recovery rather than revoking them. Confirm both NPM and the system
Certbot timer stop selecting the retired certificate.

**Transferred domain — confirmed November 1, 2026:** `meownow.app` was
transferred and is no longer owned by this homelab's operator. The former
`s3.meownow.app` endpoint is retired. Its local NPM proxy and certificate
records are disabled, and its renewal configuration is archived.
Any remaining public DNS records belong to the current domain owner's
administration. They are not pending homelab cleanup. Do not seek replacement
credentials, renew certificates, or change DNS for this domain as part of
homelab maintenance. Historical certificates and backups do not establish
current ownership or authorization.

### Checking PBS Backups

```bash
ansible proxmox_cluster -m shell -a "pvesm list mnemosyne" --become
```

## Contributing

To extend this playbook:

1. Add new roles in the `roles/` directory
2. Update `site.yml` to include the new role
3. Add corresponding defaults and example variables in `group_vars/proxmox_cluster.yml.example`
4. Update `README.md` and `AGENTS.md` with the role behavior and usage
5. Run `ansible-lint`, the main playbook syntax check, and `git diff --check`

## License

This playbook is provided as-is for managing Proxmox infrastructure.

### Speedtest Tracker

Deploy only this service with:

```bash
ansible-playbook site.yml --tags speedtest_tracker -e install_speedtest_tracker=true
```

The `speedtest_tracker` role configures an existing unprivileged Debian 13 LXC
on VLAN 40. It runs the official LinuxServer image through Debian's Docker Compose package.
This LXC uses direct Debian repositories because the local APT proxy returned
missing Release-file errors during deployment.
The image version and SHA-256 manifest digest are pinned together in role defaults.
Tests run hourly at minute 17, with automatic server selection and unlimited
SQLite result retention. The display timezone is America/Chicago.

The dashboard listens on port 80 at the container's DHCP address. Reserve its
DHCP lease for a stable URL. No public proxy or router forwarding is configured.
Data lives at `/var/lib/speedtest-tracker` inside the LXC. Back up that directory
and `/opt/speedtest-tracker/secrets.env` together before image upgrades.

The initial login is `admin@example.com`. Retrieve the randomly generated
password in your own terminal (do not paste it into chat or commit it):

```bash
ssh root@10.10.30.3 'pct exec 130 -- sed -n "s/^ADMIN_PASSWORD=//p" /opt/speedtest-tracker/secrets.env'
```

That command uses its 2026-10-02 placement on Prometheus. Resolve its current node
with `pvesh get /cluster/resources --type vm` if the container has moved.
The role preserves the encryption key, password, and database on repeat runs.

Discord notifications use an optional digest-pinned Apprise container inside
this same LXC. No extra LXC or published Apprise port is needed. Set
`speedtest_tracker_discord_enabled: true` and
`speedtest_tracker_discord_webhook_url` in ignored or Vault-encrypted variables,
then apply the `speedtest_tracker` tag. The webhook passes through stdin with
`no_log`, never through process arguments or tracked files.

The role sends Discord alerts only when scheduled tests fall below 1000 Mbps
download or 250 Mbps upload (either condition). Override these with
`speedtest_tracker_download_threshold` and `speedtest_tracker_upload_threshold`.
Routine successful results and ping alerts are disabled. Each below-threshold
hourly test can produce an alert. Existing settings are preserved before the
first managed change in `/var/lib/speedtest-tracker/.*-before-ansible.json`.
Repeat deployments do not send test messages. To stop delivery, disable Apprise
in the application and set the Ansible gate false. The gate controls configuration
management and does not erase saved settings.

Verify threshold boundaries and notification triggers without sending messages:

```bash
ssh root@10.10.30.3 'pct exec 130 -- docker exec -i -u abc -w /app/www speedtest-tracker php' \
  < roles/speedtest_tracker/files/verify-notifications.php
```

Run this from `proxmox/` after enabling notifications. Resolve current LXC
placement before using the example host and VMID.

### Homelable

The opt-in `homelable` role installs checksum-pinned Homelable 3.6.0 in an
unprivileged Debian 13 LXC. Its initial placement is Atlas, VMID 131, VLAN 40,
with DHCP, 2 cores, 4 GiB RAM, and a 12 GiB root disk. Verify live placement
before operations. The role reuses an existing container by hostname.

```bash
ansible-playbook site.yml --tags homelable --vault-password-file ~/.vaultpass
```

Set `install_homelable: true` in the ignored group variables. Caddy serves the
UI and API on port 3000. The backend listens on loopback port 8000 and runs as
`homelable` with only `CAP_NET_RAW` for ICMP discovery. Login is `admin`; retrieve the generated password with
`pct exec 131 -- cat /root/homelable-admin-password` on its hosting node.
The password is never printed by Ansible.

Preserve `/var/lib/homelable` (SQLite, uploads, and saved settings),
`/opt/homelable/app/backend/.env` (signing key and password hash), and
`/root/homelable-admin-password`. Full-container PBS backups include these.
`homelable_scanner_ranges` supplies initial ranges; change saved ranges in the
application afterward. Proxmox, OIDC, and other credentialed integrations
require separate configuration. No remote installer or updater is executed.

Check mode validates inputs and resolves placement only; it skips container
operations. Live verification checks the UI, API version, authentication,
unauthenticated rejection, credential permissions, and SQLite integrity.
A repeat run must report `changed=0`. The role refuses a different installed
release until its migration and backup procedure have been reviewed.

### Screenshot uploads (Zipline)

The `zipline` role deploys digest-pinned Zipline and PostgreSQL in an
unprivileged LXC. Enable `install_zipline` and run the `zipline` tag.
See [screenshot setup](docs/zipline.md) for ingress prerequisites and clients.

## LibreSpeed LAN bandwidth test

`librespeed-guests.yml` configures a new Terraform-owned Debian 13 guest through
SSH. Provision it with `terraform/proxmox/scripts/deploy_guest.py` and the
sanitized `guest-librespeed.profile.json.example` profile. Set `app` to
`librespeed`. Do not run this role against Proxmox hosts through `site.yml`.

The role installs pinned, checksum-verified LibreSpeed sources, nginx, and PHP
FPM directly in the guest. It disables compression, response/request buffering,
telemetry, ISP lookups, and the default 6% bandwidth compensation. Results show
application throughput, without an estimated protocol overhead adjustment.
Uploads accept 64 MiB requests. Only the three test backend PHP scripts are
served; telemetry and result-sharing PHP endpoints are unavailable.

Open the guest's private HTTP address and press **Start**. Use the direct address
without a reverse proxy, VPN, or tunnel. Download measures guest-to-client
traffic. Upload measures client-to-guest traffic. Cross-VLAN tests also measure
the router path. Browser CPU, Wi-Fi, client Ethernet speed, and shared host or
uplink traffic can limit results. Repeat a test from a wired client when you
need a baseline. No public DNS or router port-forward is required.

Reapply the same private Terraform profile to configure the service again.
The Ansible entry point can also use the private inventory in
`terraform/proxmox/artifacts/deploy/<name>/inventory.yml`. The role verifies the
web interface, worker scripts, and ping/download endpoints after installation.
It starts nginx and PHP FPM automatically after a guest reboot.

## Homebridge discovery

`homebridge-discovery.yml` publishes existing, paired HomeKit bridges on one
gateway interface through its existing Avahi D-Bus service. Use this when
unicast access to Homebridge works but its mDNS advertisements do not cross
an externally routed VLAN. UniFi does not accept its network mDNS forwarding
flag on an `UNMANAGED` network. The publisher does not change routing,
firewalls, switch ports, Homebridge configuration, or HomeKit pairing data.

The gateway must already provide Python 3, `python3-dbus`, Avahi, and systemd.
Create an ignored inventory with a `homebridge_discovery_gateways` group and
the following host variable, populated from the actual paired child bridges:

```yaml
homebridge_discovery:
  interface: br0
  hostname: homebridge-example.local
  address: 192.0.2.10
  services:
    - name: Example paired bridge
      port: 12345
      txt:
        c#: "7"
        ff: "0"
        id: "02:00:00:00:00:01"
        md: homebridge
        pv: "1.1"
        s#: "1"
        sf: "0"
        ci: "2"
```

Copy each bridge's public name, port, identity, and TXT records from its live
advertisement. Alternatively, read `_bridge.username` and `_bridge.port` from
Homebridge's config, and `displayName` and `configVersion` from the matching
`persist/AccessoryInfo.<username-without-colons>.json`. Publish only bridges
with existing paired clients. Never copy the pairing PIN, signing keys, or
paired-client keys into this inventory. The optional `sh` TXT value is the
Base64 encoding of the first four SHA-512 bytes of `setupID + username`.

Run from `proxmox/` with the private inventory:

```sh
ansible-playbook -i PATH_TO_PRIVATE_INVENTORY homebridge-discovery.yml --check --diff
ansible-playbook -i PATH_TO_PRIVATE_INVENTORY homebridge-discovery.yml
ansible-playbook -i PATH_TO_PRIVATE_INVENTORY homebridge-discovery.yml
```

The service and manifest live under `/data/homelab-homebridge-mdns`, with the
unit at `/etc/systemd/system/homebridge-mdns-proxy.service`. It re-registers
after an Avahi failure through systemd restart. It advertises only `_hap._tcp`
on the selected interface, pointing to Homebridge's existing IPv4 address.
Control traffic continues directly to Homebridge. Disable this one service
to withdraw its advertisements without changing the gateway's own relay.

The manifest is a snapshot. Refresh it after bridge identity, port, pairing,
or accessory-list changes, including the `c#` configuration version. Reapply
the playbook if a gateway firmware upgrade removes the custom service unit.
Verify discovery and service resolution with `dns-sd` from the client LAN,
then verify device control in Apple Home. Unit tests run with
`python3 tests/test_homebridge_mdns_proxy.py`.

The protected inventory and operational records for the 2026-11-02 repair
are under `terraform/proxmox/artifacts/homebridge-discovery/` at the repository
root. The guest's original VLAN interface and routes remain unchanged.
