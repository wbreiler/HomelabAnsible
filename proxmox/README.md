# Proxmox Cluster Ansible Automation

This Ansible project automates the setup of a Proxmox VE cluster with PBS backup integration, LXC container management, and system updates. Targets PVE 9 / Debian trixie.

**Cluster**: nyx (10.10.30.2), prometheus (10.10.30.3), atlas (10.10.30.9)
**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)
**Second play**: `site.yml` also applies network tuning to both proxmox_cluster and pbs_nodes groups

## Features

- **Repository Configuration**: Disables enterprise repositories (`.sources` format for PVE 9+) and configures the APT caching proxy
- **Cluster Setup**: Automatically creates a Proxmox cluster and joins all nodes
- **PBS Storage Configuration**: Connects Proxmox nodes to your Proxmox Backup Server with shared namespace support
- **ISO Management**: Automatically downloads ISOs from HTTP server, direct URLs, NFS, or SMB shares with real-time progress display
- **LXC Template Downloads**: Automatically downloads latest LXC OS templates on all nodes
- **Managed App LXCs**: Creates or adopts Apt-Cacher NG, Prowlarr, Homebridge, Spoolman, Gitea Mirror, Seerr, Pocket ID, Forgejo, Sonarr, and Radarr through repository-owned roles
- **Standalone App LXCs**: Custom installs for Discoverr (Discord bot), gallery-dl, and Stash, each opt-in and off by default
- **PBS Backup Job**: Creates/reconciles a scheduled backup job on the PBS storage, opt-in and off by default
- **VM Deployment**: Deploys full VMs from ISOs with customizable hardware (disk bus, BIOS, TPM, network model)
- **Network Tuning**: Configures storage VLAN subinterface and 10G TCP sysctl tuning (BBR, large buffers)
- **IP Tagging**: Tags LXC containers with their IP addresses in the Proxmox UI via a systemd service
- **Storage Cleanup**: Detects and optionally cleans up stale ZFS orphaned datasets from failed HA migrations
- **System Updates**: Updates Proxmox hosts and LXC operating-system packages without executing application-specific updater hooks
- **PBS Restore**: Restores LXC containers from Proxmox Backup Server backups with flexible targeting options

## Prerequisites

1. **Ansible** installed on your control machine:

   ```bash
   pip3 install ansible
   ```

2. **SSH access** to all Proxmox nodes using `~/.ssh/cluster-nash` (configured in `ansible.cfg`)

3. **PBS server** configured and accessible

## Directory Structure

```console
proxmox-ansible/
├── ansible.cfg              # Ansible configuration
├── inventory.yml            # Proxmox nodes inventory (gitignored)
├── inventory.yml.example    # Example inventory
├── site.yml                 # Main playbook
├── requirements.yml         # Ansible Galaxy collection requirements
├── group_vars/
│   ├── proxmox_cluster.yml.example  # Example configuration
│   └── proxmox_cluster.yml          # Cluster-wide variables (gitignored, vault-encrypted)
├── host_vars/               # Per-host variables (PBS config, corosync ring1, storage)
│   ├── node.yml.example     # Example host configuration
│   ├── nyx.yml              # (gitignored)
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
│   ├── gitea_mirror/        # Managed Gitea Mirror LXC
│   ├── seerr/               # Managed Seerr LXC
│   ├── pocket_id/           # Managed Pocket ID LXC
│   ├── forgejo/             # Managed Forgejo LXC
│   ├── sonarr/              # Managed Sonarr LXC
│   ├── radarr/              # Managed Radarr LXC
│   ├── discoverr_bot/       # Discoverr Discord bot LXC (custom install)
│   ├── gallery_dl/          # gallery-dl LXC (custom install)
│   ├── stash/               # Stash media server LXC (custom install)
│   ├── update_all/          # System updates role (nodes + LXCs)
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
nyx:
  ansible_host: 10.10.30.2
  proxmox_node_name: nyx
prometheus:
  ansible_host: 10.10.30.3
  proxmox_node_name: prometheus
atlas:
  ansible_host: 10.10.30.9
  proxmox_node_name: atlas
```

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
# Run only on nyx
ansible-playbook site.yml --limit nyx

# Run on multiple nodes
ansible-playbook site.yml --limit "nyx,prometheus"
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
changed: [nyx] => (item=ubuntu-22.04.iso)
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
- The cluster uses SSH-based authentication by default
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

This cluster uses a Prometheus + Grafana LXC stack (`prom-nash`, `grafana-nash` on prometheus) for monitoring.

### Standalone App LXCs

Thirteen repository-owned roles manage a single-purpose LXC. Each is opt-in and defaults off. All bootstrap through the shared `tasks/create_lxc.yml` and adopt existing containers by hostname. Because adopted containers can be HA-managed and moved by CRS auto-rebalance, each role resolves the node currently hosting its container at run time (`tasks/resolve_lxc_node.yml`); the configured `<role>_node` is only used as the target when creating a container that doesn't exist yet.

- **`apt_cacher_ng`** — Apt-Cacher NG package cache with HTTPS pass-through and self-proxy configuration. It adopts `apt-nash` (VMID 106 on `atlas`), removes its remote update hook, and uses the deployed 2 CPU, 512 MB RAM, and 25 GB configuration for replacement defaults.
- **`prowlarr`** — Prowlarr indexer manager. It adopts `prowlarr-nash` (VMID 104 on `atlas`), pins version 2.3.0.5236 and its release checksum, removes the remote update hook, and verifies the web interface.
- **`homebridge`** — HomeKit bridge. It adopts `homebridge-nash` (VMID 105 on `prometheus`), pins package version 2.0.5, checksum-verifies the Homebridge repository key, removes the remote update hook, and verifies Homebridge and Avahi.
- **`spoolman`** — 3D-printer spool inventory. It adopts `spoolman-nash` (VMID 102 on `nyx`), pins and verifies Spoolman 0.24.0 and uv 0.11.29, preserves the existing environment and SQLite data, removes the remote update hook, and verifies the API-reported version.
- **`gitea_mirror`** — Gitea Mirror repository mirroring service. It adopts `git-mirror-nash` (VMID 119, HA-managed, currently on `atlas`), pins and verifies Gitea Mirror 3.21.0 and Bun 1.3.14, preserves the existing environment file and SQLite data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the installed version.
- **`seerr`** — Seerr media-request manager (successor to Overseerr; the container was already migrated by the community script). It adopts `overseerr-nash` (VMID 117, HA-managed, currently on `atlas`), pins and verifies Seerr 3.3.0 and pnpm 10.34.4, requires the NodeSource Node.js 22 runtime, preserves `/etc/seerr/seerr.conf` and the SQLite config data, checks database integrity, backs up before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the API-reported version.
- **`pocket_id`** — Pocket ID OIDC identity provider. It adopts `pocketid-nash` (VMID 100, HA-managed, currently on `nyx`), pins and verifies the Pocket ID 2.11.0 binary, preserves the `.env` (including its encryption key) and SQLite data, checks database integrity, backs up the binary, data, and environment before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`forgejo`** — Forgejo Git hosting (serves `git.wbreiler.com`). It adopts `forgejo-nash` (VMID 103, HA-managed, currently on `prometheus`), pins and verifies the Forgejo 13.0.4 release binary, refuses downgrades and skipped major versions, preserves `app.ini` and all repository data, checks SQLite integrity, backs up the binary, config, and database before upgrades and rolls back automatically on a failed health check, removes the remote update hook, and verifies the binary-reported version.
- **`sonarr`** — Sonarr TV manager. It adopts `sonarr-nash` (VMID 110, HA-managed, currently on `atlas`), pins and verifies the Sonarr 4.0.19.2979 release, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`radarr`** — Radarr movie manager. It adopts `radarr-nash` (VMID 111, HA-managed, currently on `prometheus`), pins and verifies the Radarr 6.3.0.10514 release, preserves `config.xml` and the SQLite databases, backs up before upgrades and rolls back automatically on a failed `/ping` health check, removes the remote update hook, and verifies the API-reported version.
- **`discoverr_bot`** — Discoverr Discord bot, pinned to a commit SHA. Needs `discoverr_bot_tmdb_api_key`, `discoverr_bot_seerr_url`/`discoverr_bot_seerr_password`, and `discoverr_bot_discord_token` (put these in the vault-encrypted `group_vars/proxmox_cluster.yml`, not host_vars).
- **`gallery_dl`** — gallery-dl on a cron schedule, NFS-mounted to the vault share. Configure `gallery_dl_profiles` (usernames to archive) and optionally `gallery_dl_cookies_file`.
- **`stash`** — Stash media server, pinned to a release tag, NFS-mounted to the vault share.

```yaml
install_apt_cacher_ng: true
apt_cacher_ng_node: "atlas"
apt_cacher_ng_vmid: "106"
apt_cacher_ng_hostname: "apt-nash"
apt_cacher_ng_vlan: 40

install_prowlarr: true
prowlarr_node: "atlas"
prowlarr_vmid: "104"
prowlarr_version: "2.3.0.5236"

install_homebridge: true
homebridge_node: "prometheus"
homebridge_vmid: "105"
homebridge_version: "2.0.5"

install_spoolman: true
spoolman_node: "nyx"
spoolman_vmid: "102"
spoolman_version: "0.24.0"

install_gitea_mirror: true
gitea_mirror_node: "atlas"  # fresh-install fallback; the role finds the current host itself
gitea_mirror_vmid: "119"
gitea_mirror_version: "3.21.0"

install_seerr: true
seerr_node: "atlas"  # fresh-install fallback; the role finds the current host itself
seerr_vmid: "117"
seerr_version: "3.3.0"

install_pocket_id: true
pocket_id_node: "nyx"
pocket_id_vmid: "100"
pocket_id_version: "2.11.0"

install_forgejo: true
forgejo_node: "prometheus"
forgejo_vmid: "103"
forgejo_version: "13.0.4"  # never skip a major; upgrade one major at a time

install_sonarr: true
sonarr_node: "atlas"
sonarr_vmid: "110"
sonarr_version: "4.0.19.2979"

install_radarr: true
radarr_node: "prometheus"
radarr_vmid: "111"
radarr_version: "6.3.0.10514"

install_discoverr_bot: true
install_gallery_dl: true
install_stash: true
```

```bash
ansible-playbook -i inventory.yml site.yml --tags apt_cacher_ng -e 'install_apt_cacher_ng=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags prowlarr -e 'install_prowlarr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags homebridge -e 'install_homebridge=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags spoolman -e 'install_spoolman=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags gitea_mirror -e 'install_gitea_mirror=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags seerr -e 'install_seerr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags pocket_id -e 'install_pocket_id=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags forgejo -e 'install_forgejo=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags sonarr -e 'install_sonarr=true' --ask-vault-pass
ansible-playbook -i inventory.yml site.yml --tags radarr -e 'install_radarr=true' --ask-vault-pass
ansible-playbook site.yml --tags discoverr_bot -e 'install_discoverr_bot=true' --ask-vault-pass
ansible-playbook site.yml --tags gallery_dl -e 'install_gallery_dl=true' --ask-vault-pass
ansible-playbook site.yml --tags stash -e 'install_stash=true' --ask-vault-pass
```

After deployment, point APT clients at `http://<container-ip>:3142`. The report page is available at `http://<container-ip>:3142/acng-report.html`.

### System Updates

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
pbs_restore_node: "nyx"
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

Uses the Proxmox API to find free VMIDs in the 100-199 range and skips VMs that already exist by name.

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
```

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
# Test SSH manually
ssh -i ~/.ssh/cluster-nash root@10.10.30.2

# Verify key permissions (must be 600)
chmod 600 ~/.ssh/cluster-nash
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

# Remove node from old cluster (WARNING: destructive)
systemctl stop pve-cluster corosync
pmxcfs -l
rm /etc/pve/corosync.conf
rm -r /etc/corosync/*
killall pmxcfs
systemctl start pve-cluster
```

**Check cluster communication:**

```bash
# Verify nodes can reach each other (management network)
ping 10.10.30.2  # nyx
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

# View expected votes
pvecm expected 3  # For a 3-node cluster
```

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
4. Update `README.md`, `AGENTS.md`, and `CLAUDE.md` with the role behavior and usage
5. Run `ansible-lint`, the main playbook syntax check, and `git diff --check`

## License

This playbook is provided as-is for managing Proxmox infrastructure.
