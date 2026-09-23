# Proxmox Cluster Ansible Automation

This Ansible project automates the setup of a Proxmox VE cluster with PBS backup integration, LXC container management, and system updates. Targets PVE 9 / Debian trixie.

**Cluster**: prometheus (10.10.30.3), atlas (10.10.30.9)
**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)
**Second play**: `site.yml` also applies network tuning to both proxmox_cluster and pbs_nodes groups

## Features

- **Repository Configuration**: Disables enterprise repositories (`.sources` format for PVE 9+) and configures the APT caching proxy
- **Cluster Setup**: Automatically creates a Proxmox cluster and joins all nodes
- **PBS Storage Configuration**: Connects Proxmox nodes to your Proxmox Backup Server with shared namespace support
- **ISO Management**: Automatically downloads ISOs from HTTP server, direct URLs, NFS, or SMB shares with real-time progress display
- **LXC Template Downloads**: Automatically downloads latest LXC OS templates on all nodes
- **Managed App LXCs**: Creates or adopts Apt-Cacher NG, Prowlarr, Homebridge, Spoolman, Bambuddy, Gitea Mirror, Seerr, Pocket ID, Forgejo, Sonarr, Radarr, gallery-dl, Gatus, Diun, and a Tailscale subnet router through repository-owned roles
- **PBS Backup Job**: Creates/reconciles a scheduled backup job on the PBS storage, opt-in and off by default
- **VM Deployment**: Deploys full VMs from ISOs with customizable hardware (disk bus, BIOS, TPM, network model)
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

2. **SSH access** to all Proxmox nodes using `~/.ssh/cluster-nash` through the 1Password SSH agent and user SSH configuration

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
├── host_vars/               # Per-host variables (PBS config, corosync ring1, storage)
│   ├── node.yml.example     # Example host configuration
│   ├── prometheus.yml       # (gitignored)
│   └── atlas.yml            # (gitignored)
├── tasks/
│   ├── create_lxc.yml       # Shared LXC creation and bootstrap tasks
│   └── resolve_lxc_node.yml # Resolve the current node for an existing LXC
├── roles/
│   ├── configure_repos/     # Repository configuration role
│   ├── cluster_setup/       # Proxmox cluster creation role
│   ├── pbs_storage/         # PBS storage configuration role
│   ├── pbs_backup_job/      # PBS scheduled backup job reconciliation
│   ├── manage_isos/         # ISO management role
│   ├── iptag/               # LXC IP tagging systemd service
│   ├── download_templates/  # LXC OS template downloads
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
│   ├── gallery_dl/          # gallery-dl LXC (custom install)
│   ├── gatus/               # Managed Gatus LXC (uptime monitoring/status page)
│   ├── diun/                # Managed Diun LXC (Docker image update watcher)
│   ├── tailscale_router/    # Managed Tailscale subnet router LXC
│   ├── update_all/          # System updates role (nodes + LXCs)
│   ├── update_reminder/     # Per-node Discord update reminders
│   ├── healthcheck_reminder/# Cluster-wide Discord down-node/guest alerts
│   ├── cleanup_storage/     # Stale ZFS dataset cleanup
│   ├── pbs_restore/         # PBS backup restore role
│   ├── vm_deploy/           # Full VM deployment from ISOs
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

The tracked example also defines the `pbs_nodes` group, per-node network-tuning
settings, and non-overlapping `vmid_range_start`/`vmid_range_end` values used by
`vm_deploy`. Preserve and customize those fields rather than replacing the
example with only the abbreviated host list above.

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
- **PBS server details**: Update `pbs_server`, `pbs_datastore`, `pbs_password`
  - Note: the cluster master's `host_vars/` supplies the shared PBS username and namespace
- **ISO management**: Enable and configure ISO downloads or network shares

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

# Only set up cluster
ansible-playbook site.yml --tags cluster

# Only configure PBS storage
ansible-playbook site.yml --tags pbs

# Only manage ISOs
ansible-playbook site.yml --tags isos

# Only run system updates
ansible-playbook site.yml --tags update -e 'run_updates=true'

# Only restore from PBS backups
ansible-playbook site.yml --tags restore -e 'restore_from_pbs=true'

# Run multiple tags
ansible-playbook site.yml --tags "repos,cluster,pbs"
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

### PBS Namespaces

Proxmox storage configuration is cluster-wide. The role configures the shared PBS storage entry only on `cluster_master_node`, using that host's username and namespace. Each node can still define its own corosync ring1 address and storage pool settings. See `host_vars/node.yml.example` for the full structure.

```yaml
---
pbs_username: "pbs-nash@pbs"
pbs_namespace: "pve-nash"
corosync_ring1_addr: "10.10.50.X" # node's IP on the dedicated cluster sync network
```

Copy `host_vars/node.yml.example` for each node. Set `pbs_username` and `pbs_namespace` on the cluster master; the PBS server, datastore, and password are configured in `group_vars/proxmox_cluster.yml`.

### PBS Backup Job

The `pbs_backup_job` role creates or reconciles a scheduled backup job (`/cluster/backup`) targeting `pbs_storage_id`. It runs once, on `cluster_master_node`, since backup jobs are cluster-wide config. Opt-in and off by default — set up the job by hand in the Proxmox UI, or enable this role to manage it declaratively.

**Enable in `group_vars/proxmox_cluster.yml`:**

```yaml
configure_pbs_backup_job: true
pbs_backup_job_schedule: "0/6:30"  # every 6h30m starting at 00:00
pbs_backup_job_mode: "snapshot"
pbs_backup_job_compress: "zstd"
pbs_backup_job_vmids: ""  # empty = all guests
```

```bash
ansible-playbook site.yml --tags pbs -e 'configure_pbs_backup_job=true' --ask-vault-pass
```

### ISO Management

The `manage_isos` role supports four methods for getting ISOs onto your Proxmox nodes.

**Destructive behavior is opt-in.** By default the role only downloads/mounts; it never cancels in-progress downloads or deletes existing ISOs. Two controls, both default `false`:

- `manage_isos_cancel_in_progress: true` — kill in-progress `wget` downloads matching the storage path and remove their `.part` files.
- `manage_isos_prune_unmanaged: true` — delete any `*.iso` in `manage_isos_storage_path` not present in the configured lists (`manage_isos_http_files`, `manage_isos_downloads`, `manage_isos_files_to_copy`). Leaving this `false` protects manually uploaded ISOs from an empty or incomplete list.

#### Option 1: Download from Local HTTP Server

Configure a list of ISO filenames to fetch from an internal HTTP server:

```yaml
manage_isos: true
manage_isos_http_base_url: "http://10.10.20.3:8888" # internal ISO server
manage_isos_http_files:
  - debian-12.14.0-amd64-netinst.iso
  - ubuntu-24.04.4-amd64-live-server.iso
```

Downloads use `wget` with `.part` staging for atomic writes and real-time progress.

#### Option 2: Direct Download from URLs

```yaml
manage_isos: true
manage_isos_downloads:
  - url: "https://releases.ubuntu.com/22.04/ubuntu-22.04.3-live-server-amd64.iso"
    filename: "ubuntu-22.04.iso"
    checksum: "sha256:xxxxx" # Optional but recommended
```

**Download Progress**: The role displays real-time download progress for each ISO:

```console
TASK [manage_isos : Download ISOs from URLs with progress] ********************
changed: [atlas] => (item=ubuntu-22.04.iso)
ubuntu-22.04.iso      100%[===================>]   1.4G  15.2MB/s    in 95s
```

#### Option 3: Copy from NFS Share

```yaml
manage_isos: true
manage_isos_use_nfs: true
manage_isos_nfs_server: "192.168.1.100"
manage_isos_nfs_export: "/export/isos"
manage_isos_files_to_copy:
  - ubuntu-22.04.iso
  - debian-12.iso
```

#### Option 4: Copy from SMB/CIFS Share

```yaml
manage_isos: true
manage_isos_use_smb: true
manage_isos_smb_server: "192.168.1.100"
manage_isos_smb_share: "isos"
manage_isos_smb_mount_opts: "ro,username=user,password=pass"
manage_isos_files_to_copy:
  - ubuntu-22.04.iso
  - debian-12.iso
```

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
- **`gatus`** (`install_gatus: true`) — app-level checks and a status page/history that the script above can't give you. Creates or adopts `gatus-nash`, a small LXC running [Gatus](https://github.com/TwiN/gatus). The role builds it from a pinned, checksum-verified source tarball using a pinned, checksum-verified Go toolchain. The generated `config.yaml` probes each Proxmox node's web UI (TCP 8006), the PBS server (TCP 8007), and each enabled managed app role that defines a health URL. Add other checks through `gatus_extra_endpoints`.
- **`diun`** (`install_diun: true`) — watches configured container images for new tags or digests and sends a Discord alert. Creates or adopts `diun-nash`, a small LXC running [Diun](https://github.com/crazy-max/diun) from a pinned, checksum-verified release binary. It uses Diun's static `file` provider and the explicit `diun_watch_images` list, so it does not need Docker/API access to a target host. Checks every 6 hours by default (`diun_schedule`). `diun_first_check_notif: true` reports an image on its first scan; set `max_tags` on `watch_repo: true` entries to bound tag-history notifications.
  The dedicated LXC disables IPv6 by default (`diun_disable_ipv6: true`)
  because VLAN 40 provides IPv4 internet access but no routed IPv6; this keeps
  registry lookups from selecting unreachable AAAA records.
- **`centralized_logging`** (`install_centralized_logging: true`) — creates
  `loki-nash` with Loki and Grafana. It installs Alloy on each running non-game
  LXC and both PVE hosts. Loki keeps logs for 30 days. Grafana includes one
  dashboard for service logs, host journals, and error counts.

Together: `healthcheck_reminder` catches "is the node/guest even up" (Proxmox-native, zero footprint); `gatus` catches "is the app inside actually responding" plus gives you history and a dashboard; `diun` catches "is there a newer image available" for anything running Docker, cluster or not.

### Standalone App LXCs

Fifteen repository-owned roles in this section manage a single-purpose LXC; the Tailscale router is documented separately below. Each is opt-in and defaults off. All bootstrap through the shared `tasks/create_lxc.yml` and adopt existing containers by hostname. Because adopted containers can be HA-managed and move between nodes, each role resolves the node currently hosting its container at run time (`tasks/resolve_lxc_node.yml`); the configured `<role>_node` is only the fresh-install fallback. Names, VMIDs, sizes, nodes, and versions below are tracked defaults, not assertions about live state.

- **`apt_cacher_ng`** — Apt-Cacher NG package cache with HTTPS pass-through and self-proxy configuration. Its defaults identify `apt-nash`, VMID 106, `atlas` as the fresh-install fallback, and a 2 CPU/512 MB/25 GB container. It removes the legacy remote update hook.
- **`prowlarr`** — Prowlarr indexer manager. Its defaults identify `prowlarr-nash`, VMID 104, and `atlas` as the fresh-install fallback. It pins version 2.5.2.5491 and its release checksum, removes the remote update hook, and verifies the web interface.
- **`homebridge`** — HomeKit bridge. Its defaults identify `homebridge-nash`, VMID 105, and `prometheus` as the fresh-install fallback. It pins package version 2.0.5, checksum-verifies the Homebridge repository key, removes the remote update hook, and verifies Homebridge and Avahi.
- **`spoolman`** — 3D-printer spool inventory. Its defaults identify `spoolman-nash`, VMID 102, and `atlas` as the fresh-install fallback. It pins and verifies Spoolman 0.26.1 and uv 0.11.29, preserves the existing environment and SQLite data, removes the remote update hook, and verifies the API-reported version.
- **`bambuddy`** — Bambu Lab printer management. It creates or adopts an unprivileged Debian LXC, installs a pinned and checksum-verified Bambuddy release using the sizing recommended by the Community Scripts installer, preserves local environment and data files, and verifies the web interface on port 8000. The pinned `nils_ost.bambuddy` collection is also installed for future API-driven printer and settings management; its Docker installer is not used.
- **`gitea_mirror`** — Gitea Mirror repository mirroring service. Its defaults identify `git-mirror-nash`, VMID 119, and `atlas` as the fresh-install fallback. It pins and verifies Gitea Mirror 3.26.2 and Bun 1.3.14, preserves the existing environment file and SQLite data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the installed version.
- **`seerr`** — Seerr media-request manager. Its defaults identify `seerr-nash`, VMID 117, and `atlas` as the fresh-install fallback. It pins and verifies Seerr 3.4.1 and pnpm 10.34.4, requires Node.js 22, preserves `/etc/seerr/seerr.conf` and the SQLite config data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the API-reported version.
- **`pocket_id`** — Pocket ID OIDC identity provider. Its defaults identify `pocketid-nash`, VMID 100, and `atlas` as the fresh-install fallback. It pins and verifies the Pocket ID 2.13.0 binary, preserves the `.env` and SQLite data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`vaultwarden`** — Vaultwarden password manager. Its defaults identify `vaultwarden-nash`, VMID 125, and `atlas` as the fresh-install fallback. Based on the Community Scripts design without executing its installer, it builds pinned Vaultwarden 1.37.2 source with pinned Rust 1.97.1, installs the pinned matching web vault, preserves and verifies SQLite data, uses a hardened non-root systemd service, and rolls back failed upgrades.
- **`forgejo`** — Forgejo Git hosting. Its defaults identify `forgejo-nash`, VMID 103, and `prometheus` as the fresh-install fallback. It pins and verifies the Forgejo 16.0.2 release binary, refuses downgrades and skipped major versions, preserves `app.ini` and repository data, checks SQLite integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`sonarr`** — Sonarr TV manager. Its defaults identify `sonarr-nash`, VMID 110, and `atlas` as the fresh-install fallback. It pins and verifies Sonarr 4.0.19.2979, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`radarr`** — Radarr movie manager. Its defaults identify `radarr-nash`, VMID 111, and `prometheus` as the fresh-install fallback. It pins and verifies Radarr 6.3.0.10514, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`gallery_dl`** — gallery-dl on a cron schedule, NFS-mounted to the vault share. Configure `gallery_dl_profiles` (usernames to archive) and optionally `gallery_dl_cookies_file`.
- **`gatus`** — Uptime monitoring/status page. See [Monitoring](#monitoring) above for details.
- **`diun`** — Docker image update watcher. See [Monitoring](#monitoring) above for details.
- **`centralized_logging`** — Loki, Grafana, and Alloy. See [Centralized logging](#centralized-logging).

### Centralized logging

Grafana is available at `http://10.10.40.193:3000` over the LAN/Tailscale
subnet route. The internal NPM name is `http://graf-nash`. No internal DNS
exists, so clients need `10.10.40.86 graf-nash` in their hosts file to use
that name. The direct IP works without a hosts-file change. No public DNS
record or port forward is required or created.

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
external notification channel is configured. Uptime Kuma retains uptime
monitoring responsibility.

Game servers start in `centralized_logging_excluded_vmids`. Remove one VMID at
a time after the 30-day storage rate is known. The main PBS job includes VMID
127 because that job backs up all non-game guests. Its root disk contains
all Loki data, Grafana data, and configuration. Diun (121) is also excluded
until its 256 MiB RAM allocation can be increased safely. The router's Alloy
package is installed, and its agent runs within the existing 256 MiB limit.

The addresses above are the deployment snapshot. Reserve the DHCP leases
in the existing DHCP server to keep them stable. If an address changes,
rerun the role and update client hosts-file entries as needed.

For a delivery check, emit the same unique marker with `logger -t
homelab-logging-check MARKER` on each included host. Then run
`python3 roles/centralized_logging/files/verify_logging.py
http://10.10.40.193:3100 MARKER HOST...`. The check requires every expected
host and rejects labels outside `host`, `job`, and `unit`.

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
prowlarr_version: "2.5.2.5491"

install_homebridge: true
homebridge_node: "prometheus"
homebridge_vmid: "105"
homebridge_version: "2.0.5"

install_spoolman: true
spoolman_node: "atlas"
spoolman_vmid: "102"
spoolman_version: "0.26.1"

install_bambuddy: true
bambuddy_node: "atlas"
bambuddy_vmid: ""  # selects the next available managed-app VMID
bambuddy_version: "1.2.5.5"

install_gitea_mirror: true
gitea_mirror_node: "atlas"  # fresh-install fallback; the role finds the current host itself
gitea_mirror_vmid: "119"
gitea_mirror_version: "3.26.2"

install_seerr: true
seerr_node: "atlas"  # fresh-install fallback; the role finds the current host itself
seerr_vmid: "117"
seerr_version: "3.4.1"

install_pocket_id: true
pocket_id_node: "atlas"
pocket_id_vmid: "100"
pocket_id_version: "2.13.0"

install_vaultwarden: true
vaultwarden_node: "atlas"
vaultwarden_vmid: "125"
vaultwarden_domain: "https://vault.wbreiler.com"
# Temporarily enable signups for initial account creation, then disable them.

install_forgejo: true
forgejo_node: "prometheus"
forgejo_vmid: "103"
forgejo_version: "16.0.2"  # never skip a major; upgrade one major at a time

install_sonarr: true
sonarr_node: "atlas"
sonarr_vmid: "110"
sonarr_version: "4.0.19.2979"

install_radarr: true
radarr_node: "prometheus"
radarr_vmid: "111"
radarr_version: "6.3.0.10514"

install_gallery_dl: true

install_gatus: true
gatus_node: "atlas"
gatus_vmid: ""  # selects the next available managed-app VMID
gatus_version: "5.36.0"
gatus_discord_webhook_url: ""  # set in vault-encrypted group_vars

install_diun: true
diun_node: "atlas"
diun_vmid: ""  # selects the next available managed-app VMID
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
ansible-playbook site.yml --tags gallery_dl -e 'install_gallery_dl=true' --ask-vault-pass
ansible-playbook site.yml --tags gatus -e 'install_gatus=true' --ask-vault-pass
ansible-playbook site.yml --tags diun -e 'install_diun=true' --ask-vault-pass
ansible-playbook site.yml --tags tailscale_router -e 'install_tailscale_router=true' --ask-vault-pass
```

After deployment, point APT clients at `http://<container-ip>:3142`. The report page is available at `http://<container-ip>:3142/acng-report.html`.

### Tailscale Subnet Router

`tailscale_router` (`install_tailscale_router: true`) gives every device on your tailnet access to the whole homelab LAN without per-device WireGuard configs. It creates or adopts an unprivileged LXC (`tailscale-router-nash`), passes through `/dev/net/tun` and enables IPv4/IPv6 forwarding, installs a pinned, checksum-verified-key `tailscale` package, and runs `tailscale up --advertise-routes=...` using a reusable auth key from the Tailscale admin console (`tailscale_router_auth_key`, vault-encrypted).

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

Install the repository-owned Community Scripts application updater with:

```bash
ansible-playbook site.yml --tags update_apps -e 'install_update_apps=true' --ask-vault-pass
```

Run `update-apps --dry-run` on a Proxmox node to list eligible local LXCs. Run
`update-apps` to create a backup and invoke each existing in-container updater.
The command excludes LXCs managed by dedicated Ansible roles. It does not
download or source the upstream orchestration script.

The `update_all` role updates Proxmox hosts and operating-system packages in running LXC containers (apt for Debian/Ubuntu, apk for Alpine). It never executes application-specific updater hooks; applications managed by dedicated roles upgrade only through pinned version bumps.

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

The `pbs_restore` role restores LXC containers from Proxmox Backup Server. It supports restoring to different VMIDs, storage locations, and can optionally start containers after restore.

**Usage:**

```bash
# Restore a specific container from latest backup
ansible-playbook site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100}]}' --ask-vault-pass

# Restore to a different VMID and start after restore
ansible-playbook site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100, "target_vmid": 200, "start_after_restore": true}]}' \
  --ask-vault-pass

# Force restore (overwrite existing container)
ansible-playbook site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100, "force": true}]}' --ask-vault-pass
```

**Configuration in `group_vars/proxmox_cluster.yml`:**

```yaml
restore_from_pbs: true
pbs_restore_node: "atlas"
pbs_restore_storage: "local-lvm"
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

The `download_templates` role fetches the latest available LXC OS templates on all nodes using `pveam`. Downloads are parallelized with async polling.

Configure which templates to download in `group_vars/proxmox_cluster.yml`:

```yaml
download_lxc_templates: true # enabled by default
lxc_templates:
  - debian-12-standard
  - debian-13-standard
  - ubuntu-24.04-standard
  - alpine-3.23-default
```

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

The `vm_deploy` role deploys full VMs from ISOs. Runs on a master node and delegates `qm create` to target nodes (randomly or by name). Supports configurable hardware per VM: disk bus (virtio/scsi/ide), BIOS (seabios/ovmf), TPM 2.0, network model, and machine type (q35/pc).

Uses the Proxmox API to exclude occupied VMIDs from the per-node ranges in
`inventory.yml`, and skips VMs that already exist by name. The tracked example
partitions VMIDs 100-199 across the two nodes.

**Enable in `group_vars/proxmox_cluster.yml`:**

```yaml
deploy_vms: true
vm_deploy_node: "random" # or a specific node name
vm_deploy_storage: "local-lvm"

vm_deploy_vms:
  - name: debian-12
    iso: debian-12.14.0-amd64-netinst.iso
    ostype: l26
    cores: 2
    memory: 2048
    disk_size: 20
```

See `group_vars/proxmox_cluster.yml.example` for the full set of VM definitions and per-VM override options (node, storage, bridge, TPM, etc.).

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
  vmid_range_start: 200
  vmid_range_end: 232
```

Choose a VMID range that does not overlap any existing inventory range. The
values above are illustrative; inspect the current inventory and cluster
allocation before assigning them.

### 2. Create Host Variables

Create `host_vars/newnode.yml` from the example:

```bash
cp host_vars/node.yml.example host_vars/newnode.yml
```

Set the node-specific values. Only the cluster master needs `pbs_username` and `pbs_namespace`:

```yaml
---
pbs_username: "pbs-nash@pbs"
pbs_namespace: "pve-nash"
corosync_ring1_addr: "10.10.50.X" # node's IP on the corosync ring1 network
```

### 3. Run Playbook on New Node

Install everything on the new node:

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode
```

Or skip specific features (e.g., skip ISOs and cluster for now):

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode --skip-tags cluster,isos
```

### 4. Join to Cluster (Optional)

If you already have a cluster and want to add the new node:

```bash
ansible-playbook -i inventory.yml site.yml --limit newnode --tags cluster
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
# Test SSH using the user configuration and 1Password SSH agent
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
pvesm list pbs-backup
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
# Quick test with small Alpine ISO
ansible-playbook tests/isos-small.yml
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

## Maintenance

### Checking PBS Backups

```bash
ansible proxmox_cluster -m shell -a "pvesm list pbs-backup" --become
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
