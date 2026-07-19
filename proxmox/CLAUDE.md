# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Ansible automation project for deploying and managing a Proxmox VE cluster with Proxmox Backup Server (PBS) storage, ISO management, VM deployment, and network tuning. Ceph and Tailscale are not used in this environment. Monitoring is handled by a Prometheus + Grafana LXC stack.

**Target Environment**: Homelab infrastructure (3 Proxmox nodes: nyx/10.10.30.2, prometheus/10.10.30.3, atlas/10.10.30.9) running PVE 9 / Debian trixie.

**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)
**Second Play**: `site.yml` has two plays — the first sets up Proxmox nodes, the second runs `network_tuning` on both `proxmox_cluster` and `pbs_nodes` groups.

**SSH Key**: `~/.ssh/cluster-nash` (configured in `ansible.cfg`)

## Initial Setup

```bash
# Install the tested ansible-core and Python dependency ranges
pip install -r requirements.txt

# Install required Ansible collections
ansible-galaxy collection install -r requirements.yml

# Copy and configure required files (local .yml files are gitignored;
# sanitized *.yml.example templates are tracked)
cp inventory.yml.example inventory.yml
cp group_vars/proxmox_cluster.yml.example group_vars/proxmox_cluster.yml
cp host_vars/node.yml.example host_vars/nyx.yml  # repeat for each node
```

## Architecture

### Inventory & Configuration Model

- **Inventory**: `inventory.yml` (gitignored) - Contains node IPs
- **Group Variables**: `group_vars/proxmox_cluster.yml` (gitignored, Ansible Vault encrypted) - Cluster-wide secrets and configuration
- **Host Variables**: `host_vars/<nodename>.yml` (gitignored via `host_vars/*.yml` pattern) - Per-node corosync ring1 config and the cluster master's PBS credentials

**Critical**: All actual configuration files containing IPs, credentials, and node-specific data are gitignored. Only `.example` files are tracked in git.

### Role Execution Order

`site.yml` has two plays. The first runs on `proxmox_cluster` and executes roles sequentially:

1. **configure_repos**: Disables enterprise repos, enables no-subscription repo, configures APT proxy
2. **cluster_setup**: Creates cluster on master node, joins other nodes (conditional: `setup_cluster`)
3. **pbs_storage**: Configures PBS backup storage with shared namespace (conditional: `configure_pbs`)
4. **pbs_backup_job**: Creates/reconciles a scheduled PBS backup job on the cluster master (conditional: `configure_pbs_backup_job`)
5. **manage_isos**: Downloads/copies ISOs to nodes (conditional: `manage_isos`)
6. **iptag**: Tags LXC containers with IPs in the Proxmox UI (conditional: `install_iptag`)
7. **download_templates**: Fetches latest LXC OS templates (conditional: `download_lxc_templates`)
8. **apt_cacher_ng**: Creates or adopts an Apt-Cacher NG LXC with native tasks (conditional: `install_apt_cacher_ng`)
9. **prowlarr**: Adopts the Prowlarr LXC and manages a pinned release (conditional: `install_prowlarr`)
10. **homebridge**: Adopts the Homebridge LXC and manages a pinned Debian package (conditional: `install_homebridge`)
11. **spoolman**: Adopts the Spoolman LXC and manages pinned application and uv releases (conditional: `install_spoolman`)
12. **gitea_mirror**: Adopts the Gitea Mirror LXC and manages pinned application and Bun releases (conditional: `install_gitea_mirror`)
13. **seerr**: Adopts the Seerr LXC and manages pinned application and pnpm releases (conditional: `install_seerr`)
14. **pocket_id**: Adopts the Pocket ID LXC and manages a pinned release binary (conditional: `install_pocket_id`)
15. **forgejo**: Adopts the Forgejo LXC and manages a pinned release binary with strict upgrade guards (conditional: `install_forgejo`)
16. **sonarr**: Adopts the Sonarr LXC and manages a pinned release (conditional: `install_sonarr`)
17. **radarr**: Adopts the Radarr LXC and manages a pinned release (conditional: `install_radarr`)
18. **discoverr_bot**: Installs the Discoverr Discord bot LXC, pinned to a commit SHA (conditional: `install_discoverr_bot`)
19. **gallery_dl**: Installs a gallery-dl LXC on a cron schedule (conditional: `install_gallery_dl`)
20. **stash**: Installs the Stash media server LXC, pinned to a release tag (conditional: `install_stash`)
21. **cleanup_storage**: Detects and optionally destroys stale ZFS datasets (conditional: `run_cleanup_storage`)
22. **update_all**: Updates Proxmox nodes and LXC containers (conditional: `run_updates`)
23. **pbs_restore**: Restores LXC containers from PBS backups (conditional: `restore_from_pbs`)
24. **vm_deploy**: Deploys full VMs from ISOs (conditional: `deploy_vms`)

The second play runs on both `proxmox_cluster` and `pbs_nodes` groups:

25. **network_tuning**: Configures storage VLAN and 10G TCP sysctl tuning (tagged `network`)

Each role in the first play uses a boolean gate variable with `| default(false) | bool`. When adding a new role, follow this same pattern.

### PBS Storage Pattern

**Important**: PBS storage uses a remove-then-add pattern to ensure clean reconfiguration:

- Role checks if storage ID `backup-nash` exists
- If exists, removes it completely
- Re-adds storage with current configuration from variables

This allows updating PBS credentials or namespaces by simply re-running the playbook.

**Shared Configuration**: Storage configuration is cluster-wide and is mutated only by `cluster_master_node`. Its `host_vars` supplies the shared namespace and username; the password comes from group_vars.

### Host Variables (per-node config)

Each node's `host_vars/<nodename>.yml` can configure:

- `pbs_username` / `pbs_namespace` — shared PBS credentials on the cluster master
- `corosync_ring1_addr` — IP on the dedicated cluster sync network (10.10.50.x), used when `setup_cluster: true`

### Security Model

1. **Ansible Vault**: `group_vars/proxmox_cluster.yml` is encrypted containing:
   - PBS password
   - PBS fingerprint
   - Cluster configuration

2. **Password Protection**: PBS storage tasks use `no_log: true` and feed the password through Proxmox's interactive prompt so it does not appear in process arguments. New roles handling credentials (PBS, SMB, API tokens) must also keep secrets out of logs and argv.

3. **Gitignore Strategy**:
   - `inventory.yml` — Contains internal IPs
   - `group_vars/proxmox_cluster.yml` — Contains encrypted secrets
   - `host_vars/*.yml` — Contains node-specific config; sanitized
     `host_vars/*.yml.example` templates remain tracked

4. **LXC Privilege**: Containers bootstrapped via `tasks/create_lxc.yml` default to unprivileged; only NFS-mounting containers (stash, gallery_dl) are created privileged (kernel NFS requires it). Override with `lxc_unprivileged`.

5. **Version Pinning**: Third-party code executed or installed by roles is pinned and checksum-verified where upstream artifacts permit it. Bump versions, revisions, and checksums together after review.

## Common Commands

### Validation & Testing

```bash
# Lint all roles and playbooks (must pass before claiming changes are correct)
ansible-lint

# Validate playbook syntax
ansible-playbook -i inventory.yml site.yml --syntax-check

# List all tasks that would run
ansible-playbook -i inventory.yml site.yml --list-tasks

# Dry run (check mode) with diff output
ansible-playbook -i inventory.yml site.yml --check --diff --ask-vault-pass
```

**Always run `ansible-lint` after making changes to roles or playbooks and fix any violations before reporting the work as complete.**

### Running Playbooks

```bash
# Full deployment (requires vault password)
ansible-playbook -i inventory.yml site.yml --ask-vault-pass

# Deploy to single node (testing)
ansible-playbook -i inventory.yml site.yml --limit nyx --ask-vault-pass

# Run specific role only
ansible-playbook -i inventory.yml site.yml --tags pbs --ask-vault-pass

# Run on specific node with specific roles
ansible-playbook -i inventory.yml site.yml --limit atlas --tags pbs,update --ask-vault-pass
```

### Vault Management

```bash
# Edit encrypted vault file
ansible-vault edit group_vars/proxmox_cluster.yml

# View encrypted vault (read-only)
ansible-vault view group_vars/proxmox_cluster.yml

# Encrypt a new file
ansible-vault encrypt group_vars/proxmox_cluster.yml
```

### Node Management

```bash
# Test connectivity to all nodes
ansible all -m ping -i inventory.yml

# Test connectivity to single node
ansible nyx -m ping -i inventory.yml

# Run ad-hoc command on all nodes
ansible proxmox_cluster -i inventory.yml -a "pvecm status" --become
```

### ISO Management

```bash
# Run ISO downloads
ansible-playbook -i inventory.yml site.yml --tags isos --ask-vault-pass

# Cancel all in-progress ISO downloads on all nodes (kills wget, removes partial files)
ansible proxmox_cluster -i inventory.yml -m shell -a "bash -c '
  for pid in \$(pgrep -f \"wget.*/template/iso\" || true); do
    target=\$(tr \"\0\" \"\n\" < /proc/\$pid/cmdline | grep -A1 \"^-O\$\" | tail -1)
    [ -n \"\$target\" ] && rm -f \"\$target\"
    kill \"\$pid\" || true
  done
  rm -f /var/lib/vz/template/iso/*.part
'" --become
```

### System Updates

```bash
# Update all nodes and LXCs
ansible-playbook -i inventory.yml site.yml --tags update --ask-vault-pass

# Update nodes only (skip LXCs)
ansible-playbook -i inventory.yml site.yml --tags update \
  -e 'update_lxcs=false' --ask-vault-pass

# Update LXCs only (skip nodes)
ansible-playbook -i inventory.yml site.yml --tags update \
  -e 'update_nodes=false' --ask-vault-pass

# Update with auto-reboot if kernel updated
ansible-playbook -i inventory.yml site.yml --tags update \
  -e 'update_reboot_if_required=true' --ask-vault-pass
```

### PBS Restore

```bash
# Restore specific container from latest backup
ansible-playbook -i inventory.yml site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100}]}' --ask-vault-pass

# Restore to different VMID and start after restore
ansible-playbook -i inventory.yml site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100, "target_vmid": 200, "start_after_restore": true}]}' \
  --ask-vault-pass

# Force restore (overwrite existing container)
ansible-playbook -i inventory.yml site.yml --tags restore \
  -e '{"pbs_restore_containers": [{"vmid": 100, "force": true}]}' --ask-vault-pass
```

### Tests (localhost only, no Proxmox needed)

```bash
# Test ISO download with a small Alpine ISO (~60MB)
ansible-playbook tests/isos-small.yml

# Cleanup after tests
rm -rf /tmp/test-isos
```

## Adding New Nodes

1. Update `inventory.yml`:
   - Add new node with `ansible_host`, `proxmox_node_name`, `vmid_range_start`, `vmid_range_end` (used by vm_deploy for VMID allocation)
2. Create `host_vars/<nodename>.yml` from `host_vars/node.yml.example`:
   - Set `pbs_username` and `pbs_namespace`
   - Set `corosync_ring1_addr` if using ring1
3. Run playbook with `--limit` flag to target new node only

## Adding New Roles

1. Create role structure: `roles/role_name/{tasks,defaults,handlers}/main.yml`
2. Add role to `site.yml` with a boolean gate variable and tags:

   ```yaml
   - role: your_role
     when: enable_your_role | default(false) | bool
     tags: ["your_role", "category"]
   ```

   Use the `| default(false) | bool` pattern so roles are opt-in by default.

3. Add gate variable (default `false`) and any config vars to `group_vars/proxmox_cluster.yml.example`
4. Update README.md documentation

## Role-Specific Notes

### configure_repos Role

- Disables Proxmox enterprise apt repo (`pve-enterprise.sources`) and Ceph enterprise repo (`ceph.sources`) by setting `Enabled: false`
- Handles both `.sources` (PVE 9 / Debian trixie) and legacy `.list` formats
- Only adds a no-subscription repo file if `pve-no-subscription` is not already present in `proxmox.sources`
- Configures APT proxy at `10.10.40.175:3142` (the `apt-cacher-ng` LXC, VMID 106 on nyx) via `/etc/apt/apt.conf.d/99proxy`
- APT proxy is controlled by `configure_apt_proxy` (default `true`); host/port configurable via `apt_proxy_host`/`apt_proxy_port`

### pbs_storage Role

- **Critical**: Always removes existing PBS storage before re-adding to ensure clean state
- Uses `no_log: true` for security when handling passwords
- Runs only on `cluster_master_node` because storage configuration is cluster-wide
- Namespace and username come from the cluster master's host_vars; password from group_vars

### pbs_backup_job Role

- Creates or reconciles a scheduled backup job (`/cluster/backup`) targeting `pbs_storage_id`
- Runs once, delegated to `cluster_master_node`, because backup jobs are cluster-wide config
- Diffs schedule, mode, compress, and VMID selection against the existing job; only calls `pvesh set` when something changed
- Skipped by default unless `configure_pbs_backup_job: true`

### cluster_setup Role

- Master node (set via `cluster_master_node`) creates cluster first; other nodes join
- Uses corosync for cluster communication with optional ring1 (set `corosync_ring1_addr` in host_vars)
- Cluster join feeds `cluster_password` to pvecm's interactive prompt via `ansible.builtin.expect` (installs `python3-pexpect`) so the password never appears in the process list
- Skipped by default unless `setup_cluster: true`
- **Note**: Cluster status verification uses `failed_when: false` to handle non-clustered nodes gracefully

### manage_isos Role

- Supports four methods: HTTP server download, direct URL download, NFS mount, SMB/CIFS mount
- HTTP downloads use `wget` with `.part` staging for atomic writes and real-time progress
- Downloads to `/var/lib/vz/template/iso/`
- Skips downloads if ISO already exists (idempotent); verifies checksums if provided
- Skipped by default unless `manage_isos: true`
- Cancelling in-progress downloads and pruning unmanaged ISOs are separate default-false controls (`manage_isos_cancel_in_progress`, `manage_isos_prune_unmanaged`); leaving both false never touches pre-existing files

### apt_cacher_ng, prowlarr, homebridge, spoolman, gitea_mirror, seerr, pocket_id, forgejo, sonarr, radarr, discoverr_bot, gallery_dl, stash Roles

- Repository-owned single-purpose LXC roles, each bootstrapped through the shared `tasks/create_lxc.yml`
- Each resolves the node currently hosting its container at run time via the shared `tasks/resolve_lxc_node.yml` (all CTs are HA-managed and CRS auto-rebalance can move them); `<role>_node` is only the fallback for creating a container that doesn't exist yet
- `apt_cacher_ng` installs distribution packages, removes the legacy remote updater, manages HTTPS pass-through and self-proxy configuration, and adopts `apt-nash` (VMID 106 on `atlas`)
- `prowlarr` adopts `prowlarr-nash` (VMID 104 on `atlas`), pins version 2.3.0.5236 and its release checksum, and manages the service and health check
- `homebridge` adopts `homebridge-nash` (VMID 105 on `prometheus`), pins package version 2.0.5, verifies the repository key, and manages the APT source and service health
- `spoolman` adopts `spoolman-nash` (VMID 102 on `nyx`), preserves its environment and SQLite data, pins Spoolman and uv releases, and verifies the reported application version
- `gitea_mirror` adopts `git-mirror-nash` (VMID 119, HA-managed, currently on `atlas`), pins Gitea Mirror 3.21.0 and Bun 1.3.14 releases with checksums, preserves the environment file and SQLite data, refuses destructive 2.x migrations, backs up before upgrades with automatic rollback on failed health checks, and verifies the installed version
- `seerr` adopts `overseerr-nash` (VMID 117, HA-managed, currently on `atlas`), pins Seerr 3.3.0 and pnpm 10.34.4 with checksums, requires NodeSource Node.js 22, preserves `/etc/seerr/seerr.conf` and the SQLite config data, refuses to overwrite an unmigrated Overseerr install, backs up before upgrades with automatic rollback on failed health checks, and verifies the API-reported version
- `pocket_id` adopts `pocketid-nash` (VMID 100, HA-managed, currently on `nyx`), pins the Pocket ID 2.11.0 release binary with a checksum, preserves the `.env` (including its encryption key) and SQLite data, backs up binary, data, and environment before upgrades with automatic rollback on failed health checks, and verifies the binary-reported version
- `forgejo` adopts `forgejo-nash` (VMID 103, HA-managed, currently on `prometheus` — it serves `git.wbreiler.com`, this repo's remote), pins the Forgejo 13.0.4 release binary with a checksum, refuses downgrades and skipped major versions, preserves `app.ini` and repository data, backs up binary, config, and SQLite database before upgrades with automatic rollback on failed health checks, and verifies the binary-reported version
- `sonarr` adopts `sonarr-nash` (VMID 110, HA-managed, currently on `atlas`), pins the Sonarr 4.0.19.2979 release with a checksum, preserves `config.xml` and the SQLite databases, backs up before upgrades with automatic rollback on failed `/ping` checks, and verifies the API-reported version
- `radarr` adopts `radarr-nash` (VMID 111, HA-managed, currently on `prometheus`), pins the Radarr 6.3.0.10514 release with a checksum, preserves `config.xml` and the SQLite databases, backs up before upgrades with automatic rollback on failed `/ping` checks, and verifies the API-reported version
- `discoverr_bot` and `stash` pin third-party code (`discoverr_bot_repo_version` commit SHA, `stash_version` release tag)
- `gallery_dl` and `stash` NFS-mount the vault share and are created privileged (kernel NFS requires it)
- `discoverr_bot` secrets (TMDB key, Discord token, Seerr password) must go in vault-encrypted group_vars, not host_vars or role defaults
- Each skipped by default unless its `install_*` var is `true`

### update_all Role

- Updates both Proxmox host nodes and all running LXC containers
- For each container: detects package manager, updates OS packages (apt or apk)
- Never executes application-specific updater hooks; managed applications upgrade only through pinned role version bumps
- Uses `pct exec` to run commands inside containers
- Optional auto-reboot if kernel updates detected; can skip specific containers by VMID
- Skipped by default unless `run_updates: true`

### pbs_restore Role

- Restores LXC containers from Proxmox Backup Server
- Supports restoring to different VMIDs and storage locations; can restore specific snapshots or latest
- Optional force mode to overwrite existing containers
- Runs on a single target node (`pbs_restore_node`)
- Skipped by default unless `restore_from_pbs: true`

### iptag Role

- Installs a repository-owned Python systemd service that tags LXCs and VMs with IPs in the Proxmox UI
- Manages `/opt/iptag/iptag.py`, its configuration, the `iptag-run` command, and the systemd unit directly with Ansible
- Migrates the legacy unit from `/lib/systemd/system` to `/etc/systemd/system`
- Reconciles configuration changes idempotently and validates the rendered configuration before starting the service
- Enabled by default (`install_iptag: true`)
- Configurable: `iptag_tag_format_choice` (1=last two octets, 2=last octet, 3=full), `iptag_loop_interval`, `iptag_allowed_cidrs`, `iptag_debug`, and `iptag_command_timeout`

### download_templates Role

- Fetches latest LXC OS templates via `pveam` on all nodes
- Resolves the latest available version for each prefix (not pinning specific filenames)
- Uses parallel async downloads with a 40-retry, 15s-delay wait loop
- Enabled by default (`download_lxc_templates: true`)
- Template list configurable via `lxc_templates` var; storage via `template_storage`

### cleanup_storage Role

- Two-phase: first reports stale ZFS orphaned datasets, only destroys if `cleanup_storage_destroy_stale: true`
- Also reports LXC configs referencing ZFS datasets missing on the current node
- **Always dry-run by default** — safe to run without risk of data loss
- ZFS pool/dataset path configurable via `cleanup_storage_zfs_pool` / `cleanup_storage_zfs_dataset`

### vm_deploy Role

- Deploys full VMs from ISOs by building `qm create` commands with Jinja2 conditionals
- Runs on `vm_deploy_master_node` (default: nyx), delegates `qm create` to target nodes
- Auto-assigns VMIDs from the 100-199 range via `pvesh get /cluster/resources`
- Supports `random` for both target node and storage pool selection
- Idempotent by VM name — skips VMs that already exist
- Per-VM overrides for node, storage, bridge, disk bus, BIOS, TPM, machine type, network model

### network_tuning Role

- Runs as a separate play (play 2 of `site.yml`) on both `proxmox_cluster` and `pbs_nodes` groups
- Configures a VLAN subinterface via `blockinfile` in `/etc/network/interfaces`
- Applies sysctl settings with `reload: true` for immediate effect
- Loads and persists `tcp_bbr` kernel module
- Triggers `ifreload -a` handler when VLAN config changes
- VLAN config guarded by `network_tuning_storage_vlan_ip | length > 0`

## Ansible Configuration

- **Fact Caching**: Enabled with 1-hour timeout, stored in `.ansible/facts/`
- **Host Key Checking**: Disabled (homelab environment)
- **SSH Pipelining**: Enabled for performance
- **Privilege Escalation**: Automatic sudo to root

## Git Workflow

**Important**: This project uses extensive gitignore to protect sensitive data:

- Never commit `inventory.yml`, `group_vars/proxmox_cluster.yml`, or `host_vars/*.yml`
- Only commit `.example` files and role code
- Always check `git status` before committing to ensure no sensitive files are staged
- Creating commits is allowed without asking; **never push** — the user pushes once everything is complete

### Commit Conventions

Use conventional commit format: `role_name: brief description`. Examples:

- `configure_repos: add apt proxy host/port to defaults`
- `vm_deploy: add TPM 2.0 support`
- `docs: update README with new role sections`

Always run `ansible-lint` before committing and fix any violations.
