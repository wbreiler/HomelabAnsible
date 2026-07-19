# AI Assistant Context: Proxmox Ansible Automation

This file provides guidance to AI code assistants when working with code in this repository.

## Project Overview

This is an Ansible automation project for deploying and managing a Proxmox VE cluster. It handles repository configuration, cluster formation, Proxmox Backup Server (PBS) storage, ISO management, LXC/VM deployment, network tuning, and system updates.

**Target Environment**: Homelab infrastructure (3 Proxmox nodes: nyx/10.10.30.2, prometheus/10.10.30.3, atlas/10.10.30.9) running PVE 9 / Debian trixie.

**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)

**Key Decisions**:

* This environment does not use Ceph or Tailscale.
* Monitoring is handled by a Prometheus + Grafana LXC stack.
* The main playbook `site.yml` has two plays: the first sets up Proxmox nodes, the second runs `network_tuning` on both `proxmox_cluster` and `pbs_nodes` groups.
* The SSH key `~/.ssh/cluster-nash` is configured in `ansible.cfg`.

## Project Structure

* **`site.yml`**: The main entry point playbook. Orchestrates the execution of roles.
* **`inventory.yml`**: (Gitignored) Defines the Proxmox hosts (IPs, names). See `inventory.yml.example`.
* **`group_vars/proxmox_cluster.yml`**: (Gitignored) Cluster-wide configuration and secrets (often Vault-encrypted). See `group_vars/proxmox_cluster.yml.example`.
* **`host_vars/`**: (Gitignored) Per-host configuration (PBS namespaces, corosync, ZFS). See `host_vars/node.yml.example`.
* **`roles/`**: Contains the logic for specific tasks:
  * `configure_repos`: Sets up Proxmox repositories (disables enterprise, enables no-subscription).
  * `cluster_setup`: Creates or joins a Proxmox cluster.
  * `pbs_storage`: Configures Proxmox Backup Server storage with shared namespace.
  * `manage_isos`: Downloads or mounts ISOs.
  * `iptag`: Tags LXC containers with IPs in the Proxmox UI.
  * `download_templates`: Fetches latest LXC OS templates.
  * `apt_cacher_ng`: Creates and configures a repository-owned Apt-Cacher NG LXC.
  * `prowlarr`: Creates or adopts the Prowlarr LXC with a pinned, checksum-verified release.
  * `homebridge`: Creates or adopts the Homebridge LXC with a pinned Debian package.
  * `spoolman`: Creates or adopts the Spoolman LXC with pinned application and uv releases.
  * `gitea_mirror`: Creates or adopts the Gitea Mirror LXC with pinned application and Bun releases.
  * `seerr`: Creates or adopts the Seerr LXC with pinned application and pnpm releases.
  * `pocket_id`: Creates or adopts the Pocket ID LXC with a pinned release binary.
  * `forgejo`: Creates or adopts the Forgejo LXC with a pinned release binary and strict upgrade guards.
  * `sonarr`: Creates or adopts the Sonarr LXC with a pinned, checksum-verified release.
  * `radarr`: Creates or adopts the Radarr LXC with a pinned, checksum-verified release.
  * `cleanup_storage`: Detects and optionally destroys stale ZFS datasets.
  * `update_all`: Updates Proxmox host nodes and LXC containers.
  * `pbs_restore`: Restores LXC containers from PBS backups.
  * `vm_deploy`: Deploys full VMs from ISOs.
  * `network_tuning`: Configures storage VLAN and 10G TCP sysctl tuning.
* **`ansible.cfg`**: Project-specific Ansible configuration.

## Initial Setup

```bash
# Install Ansible if not already present
pip install ansible

# Install remaining Python dependencies
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

* **Inventory**: `inventory.yml` (gitignored) - Contains node IPs and VMID ranges.
* **Group Variables**: `group_vars/proxmox_cluster.yml` (gitignored, Ansible Vault encrypted) - Cluster-wide secrets and configuration.
* **Host Variables**: `host_vars/<nodename>.yml` (gitignored via `host_vars/*.yml` pattern) - Per-node PBS, corosync ring1, and ZFS storage pool config.

**Critical**: All actual configuration files containing IPs, credentials, and node-specific data are gitignored. Only `.example` files are tracked in git.

### Role Execution Order

`site.yml` has two plays. The first runs on `proxmox_cluster` and executes roles sequentially. Each role is gated by a boolean variable (`when: role_gate_variable | default(false) | bool`).

1. **configure_repos**: Disables enterprise repos, enables no-subscription repo, configures APT proxy.
2. **cluster_setup**: Creates cluster on master node, joins other nodes.
3. **pbs_storage**: Configures PBS backup storage with shared namespace.
4. **manage_isos**: Downloads/copies ISOs to nodes.
5. **iptag**: Tags LXC containers with IPs in the Proxmox UI.
6. **download_templates**: Fetches latest LXC OS templates.
7. **apt_cacher_ng**: Creates or adopts an Apt-Cacher NG LXC and manages it with native tasks.
8. **prowlarr**: Creates or adopts the Prowlarr LXC and manages a pinned release.
9. **homebridge**: Creates or adopts the Homebridge LXC and manages a pinned package.
10. **spoolman**: Creates or adopts the Spoolman LXC and manages pinned application and uv releases.
11. **gitea_mirror**: Creates or adopts the Gitea Mirror LXC and manages pinned application and Bun releases.
12. **seerr**: Creates or adopts the Seerr LXC and manages pinned application and pnpm releases.
13. **pocket_id**: Creates or adopts the Pocket ID LXC and manages a pinned release binary.
14. **forgejo**: Creates or adopts the Forgejo LXC and manages a pinned release binary with strict upgrade guards.
15. **sonarr**: Creates or adopts the Sonarr LXC and manages a pinned release.
16. **radarr**: Creates or adopts the Radarr LXC and manages a pinned release.
17. **cleanup_storage**: Detects and optionally destroys stale ZFS datasets.
18. **update_all**: Updates Proxmox nodes and LXC containers.
19. **pbs_restore**: Restores LXC containers from PBS backups.
20. **vm_deploy**: Deploys full VMs from ISOs.

The second play runs on both `proxmox_cluster` and `pbs_nodes` groups:

21. **network_tuning**: Configures storage VLAN and 10G TCP sysctl tuning (tagged `network`).

### PBS Storage Pattern

**Important**: The `pbs_storage` role uses a remove-then-add pattern to ensure clean reconfiguration. Proxmox storage configuration is cluster-wide, so the role runs only on `cluster_master_node`, using that host's PBS credentials and namespace.

### Host Variables (per-node config)

Each node's `host_vars/<nodename>.yml` configures:

* `pbs_username` / `pbs_namespace` — Shared PBS credentials configured on the cluster master.
* `corosync_ring1_addr` — IP on the dedicated cluster sync network (10.10.50.x).
* `storage_pools` — ZFS pool definitions (name, raid type, disk IDs).

### Security Model

1. **Ansible Vault**: `group_vars/proxmox_cluster.yml` is encrypted and contains secrets like the PBS password and fingerprint.
2. **Password Protection**: Tasks handling credentials (e.g., `pbs_storage`) must use `no_log: true` and must not place secrets in process arguments. Use a supported prompt, stdin, or secret-file mechanism.
3. **Gitignore Strategy**: `inventory.yml`, `group_vars/proxmox_cluster.yml`, and `host_vars/*.yml` are all gitignored to protect sensitive data. Their sanitized `*.yml.example` templates remain tracked.
4. **Installer Integrity**: Third-party releases and source revisions are pinned and checksum-verified before root executes or installs them. Bump versions and checksums together after reviewing upstream changes.

## Development Conventions

* **Secrets Management**: NEVER commit sensitive files. Use the provided `.example` files as templates.
* **Idempotency**: Ensure all tasks are idempotent. The playbook should be safely runnable multiple times.
* **Privilege Escalation**: The playbook runs with `become: true` by default (sudo to root).
* **Linting**: Adhere to standard Ansible linting practices. **Always run `ansible-lint` and fix violations before reporting work as complete.**
* **Git Commits**:
  * Creating commits is allowed without asking. **Never push** — the user pushes once everything is complete.
  * Use `<scope>: <imperative summary>` for the subject, matching the existing history (for example, `homebridge: replace remote installer with managed tasks`).
  * Add a blank line followed by a concise, wrapped body that explains why the change was needed and what behavior changed.
  * Add a blank line before a truthful `Co-Authored-By` trailer for AI-assisted changes; use the actual assistant identity rather than copying another tool's attribution.

## Common Commands

### Validation & Testing

```bash
# Lint all roles and playbooks (must pass)
ansible-lint

# Validate playbook syntax
ansible-playbook -i inventory.yml site.yml --syntax-check

# Dry run (check mode) with diff output
ansible-playbook -i inventory.yml site.yml --check --diff --ask-vault-pass
```

### Running Playbooks

```bash
# Full deployment (requires vault password)
ansible-playbook -i inventory.yml site.yml --ask-vault-pass

# Deploy to a single node
ansible-playbook -i inventory.yml site.yml --limit nyx --ask-vault-pass

# Run a specific role only by using tags
ansible-playbook -i inventory.yml site.yml --tags pbs --ask-vault-pass

# Run specific roles on a specific node
ansible-playbook -i inventory.yml site.yml --limit atlas --tags "pbs,update" --ask-vault-pass
```

### Tags for Granular Execution

* `repos`: Configure repositories only.
* `cluster`: Run cluster setup logic.
* `pbs`: Configure PBS storage.
* `isos`: Manage ISO downloads/mounts.
* `update`: Update nodes and LXC containers (requires `-e 'run_updates=true'`).
* `restore`: Restore containers from PBS backups (requires `-e 'restore_from_pbs=true'`).
* `network`: Apply network tuning.

### Vault Management

```bash
# Edit encrypted vault file
ansible-vault edit group_vars/proxmox_cluster.yml

# View encrypted vault (read-only)
ansible-vault view group_vars/proxmox_cluster.yml
```

### Node Management

```bash
# Test connectivity to all nodes
ansible all -m ping -i inventory.yml

# Run ad-hoc command on all cluster nodes
ansible proxmox_cluster -i inventory.yml -a "pvecm status" --become
```

### Role-Specific Commands

See the `CLAUDE.md` or `README.md` files for extensive examples of role-specific commands for ISO management, LXC installation, system updates, and PBS restores.

## Adding New Nodes

1. **Update `inventory.yml`**: Add the new node with `ansible_host`, `proxmox_node_name`, and `vmid_range_start`/`end`.
2. **Create `host_vars/<nodename>.yml`**: Copy `host_vars/node.yml.example` and populate `corosync_ring1_addr` and `storage_pools`; set `pbs_username` and `pbs_namespace` on the cluster master only.
3. **Run Playbook**: Run the playbook with `--limit <nodename>` to target the new node.

## Adding New Roles

1. Create the role structure: `roles/role_name/{tasks,defaults,handlers}/main.yml`.
2. Add the role to `site.yml` with a boolean gate variable and tags:

    ```yaml
    - role: your_role
      when: enable_your_role | default(false) | bool
      tags: ["your_role", "category"]
    ```

3. Add the gate variable (default `false`) and any config vars to `group_vars/proxmox_cluster.yml.example`.
4. Update `README.md` and this file with documentation for the new role.

## Role-Specific Notes

### configure_repos

* Disables Proxmox enterprise and Ceph enterprise repos by setting `Enabled: false` in `.sources` files (PVE 9+).
* Configures an APT proxy via `apt_proxy_host`/`apt_proxy_port` variables.

### pbs_storage

* **Critical**: Always removes existing PBS storage before re-adding to ensure a clean state.
* Uses `no_log: true` for security when handling passwords.

### cluster_setup

* The `cluster_master_node` creates the cluster; other nodes join.
* Skipped by default unless `setup_cluster: true`.

### manage_isos

* Supports HTTP, direct URL, NFS, and SMB/CIFS methods.
* HTTP/URL downloads use `wget` with `.part` staging for atomic writes and progress display.
* Cancelling in-progress downloads (`manage_isos_cancel_in_progress`) and pruning unmanaged ISOs (`manage_isos_prune_unmanaged`) are separate, default-`false` controls.

### apt_cacher_ng

* Manages Apt-Cacher NG with repository-owned Ansible tasks.
* Creates or adopts an LXC by hostname on `apt_cacher_ng_node`.
* Installs `apt-cacher-ng` and `avahi-daemon`, removes the legacy remote updater, configures HTTPS pass-through and the local APT proxy, and verifies the service.
* Skipped by default unless `install_apt_cacher_ng: true`.

### prowlarr

* Manages Prowlarr with repository-owned Ansible tasks.
* Adopts `prowlarr-nash` (VMID 104 on `atlas`) without reinstalling the existing application.
* Pins the Prowlarr release and checksum, manages dependencies, data directory, service, and health checks, and removes the remote updater.
* Skipped by default unless `install_prowlarr: true`.

### homebridge

* Manages Homebridge with repository-owned Ansible tasks.
* Adopts `homebridge-nash` (VMID 105 on `prometheus`) without replacing its data.
* Pins the Homebridge Debian package and checksum-verifies its repository key, manages the APT source and package pin, and removes the remote updater.
* Skipped by default unless `install_homebridge: true`.

### spoolman

* Manages Spoolman with repository-owned Ansible tasks.
* Adopts `spoolman-nash` (VMID 102 on `nyx`) while preserving its `.env` file and SQLite data directory.
* Pins and checksum-verifies both Spoolman and uv releases, builds dependencies before atomically swapping the application, removes the remote updater, and verifies the reported application version.
* Skipped by default unless `install_spoolman: true`.

### gitea_mirror

* Manages Gitea Mirror with repository-owned Ansible tasks.
* Adopts `git-mirror-nash` (VMID 119, HA-managed, currently on `atlas`) while preserving its environment file and SQLite data directory; the role resolves the current hosting node at run time, and `gitea_mirror_node` is only the fresh-install fallback.
* Pins and checksum-verifies both Gitea Mirror and Bun releases, refuses destructive 2.x migrations, checks SQLite integrity before upgrades, builds the new release before stopping the service, keeps a pre-upgrade backup, rolls back automatically when the upgraded service fails its health check, removes the remote updater, and verifies the installed version.
* Skipped by default unless `install_gitea_mirror: true`.

### seerr

* Manages Seerr with repository-owned Ansible tasks.
* Adopts `overseerr-nash` (VMID 117, HA-managed, currently on `atlas`) while preserving `/etc/seerr/seerr.conf` and the SQLite config data; the container was already migrated from Overseerr to Seerr by its legacy updater.
* Pins and checksum-verifies both Seerr and pnpm releases, requires NodeSource Node.js 22, refuses to overwrite an unmigrated Overseerr install, checks SQLite integrity before upgrades, builds the new release before stopping the service, keeps a pre-upgrade backup, rolls back automatically when the upgraded service fails its health check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_seerr: true`.

### pocket_id

* Manages Pocket ID with repository-owned Ansible tasks.
* Adopts `pocketid-nash` (VMID 100, HA-managed, currently on `nyx`) while preserving its `.env` (including the mandatory encryption key) and SQLite data.
* Pins and checksum-verifies the single release binary, checks SQLite integrity before upgrades, backs up the binary, data, and environment before swapping, rolls back automatically (including the data directory, since new versions migrate the schema on start) when the upgraded service fails its health check, removes the remote updater, and verifies the binary-reported version.
* Skipped by default unless `install_pocket_id: true`.

### forgejo

* Manages Forgejo with repository-owned Ansible tasks.
* Adopts `forgejo-nash` (VMID 103, HA-managed, currently on `prometheus`), which serves `git.wbreiler.com` — this repository's own remote. Preserves `app.ini` and all repository data.
* Pins and checksum-verifies the release binary, refuses downgrades and skipped major versions (Forgejo must upgrade one major at a time), checks SQLite integrity before upgrades, stages and sanity-runs the new binary before stopping the service, backs up the binary, config, and database (not the multi-GB repositories, which upgrades never rewrite), rolls back binary, database, and config automatically when the upgraded service fails its health check, removes the remote updater, and verifies the binary-reported version.
* Skipped by default unless `install_forgejo: true`.

### sonarr

* Manages Sonarr with repository-owned Ansible tasks.
* Adopts `sonarr-nash` (VMID 110, HA-managed, currently on `atlas`) while preserving `config.xml` and the SQLite databases; the service keeps running as the `media` user with its in-container NFS media mounts untouched.
* Pins and checksum-verifies the release tarball, backs up config and databases before atomically swapping the install directory, rolls back automatically when the upgraded service fails its `/ping` check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_sonarr: true`.

### radarr

* Manages Radarr with repository-owned Ansible tasks.
* Creates or adopts `radarr-nash` (VMID 111 on `prometheus`) while preserving `config.xml` and the SQLite database; the service runs as the `media` user.
* Pins and checksum-verifies the release tarball, backs up config and database state before atomically swapping the install directory, rolls back automatically when the upgraded service fails its `/ping` check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_radarr: true`.

### update_all

* Updates both Proxmox hosts and all running LXC containers.
* For each container: detects package manager (apt/apk) and updates OS packages.
* Never executes application-specific updater hooks; managed applications upgrade only through pinned role version bumps.

### pbs_restore

* Restores LXC containers from PBS.
* Runs on a single target node (`pbs_restore_node`).

### iptag

* Installs a repository-owned Python service that tags LXC containers and VMs with their IP addresses in the Proxmox UI.
* Enabled by default (`install_iptag: true`).
* Manages the runtime, configuration, manual `iptag-run` command, and systemd unit directly with Ansible.
* Migrates existing installs from `/lib/systemd/system/iptag.service` to an Ansible-managed unit in `/etc/systemd/system`.
* Configurable with `iptag_tag_format_choice`, `iptag_loop_interval`, `iptag_allowed_cidrs`, `iptag_debug`, and `iptag_command_timeout`.

### download_templates

* Fetches latest LXC OS templates via `pveam` on all nodes using parallel async downloads.
* Enabled by default (`download_lxc_templates: true`).

### cleanup_storage

* Reports stale/orphaned ZFS datasets.
* **Always dry-run by default**. Only destroys if `cleanup_storage_destroy_stale: true`.

### vm_deploy

* Deploys full VMs from ISOs by building `qm create` commands.
* Runs on `vm_deploy_master_node` and delegates creation to target nodes.
* Auto-assigns VMIDs from the 100-199 range.
* Idempotent by VM name.

### network_tuning

* Runs as a separate play on both `proxmox_cluster` and `pbs_nodes`.
* Configures a VLAN subinterface and applies TCP sysctl tuning (e.g., BBR).

## Ansible Configuration (`ansible.cfg`)

* **Fact Caching**: Enabled with a 1-hour timeout.
* **Host Key Checking**: Disabled (`host_key_checking = False`) for this homelab environment.
* **SSH Pipelining**: Enabled for performance.
* **Privilege Escalation**: `become = true` is set globally.
