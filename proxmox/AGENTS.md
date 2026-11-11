# AI Assistant Context: Proxmox Ansible Automation

This file provides guidance to AI code assistants when working with code in this repository.

## Guest provisioning ownership

Terraform owns the existing guests. Do not add guest creation, startup,
resizing, boot flags, or hardware mutation to application roles. The shared
`tasks/create_lxc.yml` is now an existing-guest software bootstrap, despite its
legacy filename. It fails for absent or stopped guests. `vm_deploy` and
`macos.yml` refuse provisioning. Preserve application configuration tasks.

Terraform also owns backup jobs, HA resources/rules, the PBS storage connection,
and cached images/templates. Never reconnect pbs_storage, pbs_backup_job,
manage_isos, or download_templates to site.yml. Their direct role entry points
fail deliberately. HA runtime placement/power and IP tags retain their existing
services. Terraform ignores runtime HA node/power state and service-maintained tags. Raw LXC passthrough entries
remain preserved in PVE and protected local snapshots. The provider does not
represent every raw LXC setting. Do not claim that import proves disaster recovery.

## Project Overview

This project configures Proxmox hosts and existing guest software. It manages
repositories, optional cluster formation, network tuning, monitoring, updates,
and explicit recovery operations. Terraform owns guest and platform resources.

**Target Environment**: Homelab infrastructure (2 Proxmox nodes: prometheus/10.10.30.3 and atlas/10.10.30.9) running PVE 9 / Debian trixie.

**PBS Server**: mnemosyne (10.10.20.2, `pbs_nodes` inventory group)

**Key Decisions**:

* This environment does not use Ceph. Tailscale is confined to the opt-in
  `tailscale_router` LXC and is not installed on cluster nodes.
* Gatus and Diun are opt-in monitoring roles; Discord update and health
  reminders are also managed here.
* The main playbook `site.yml` has two plays: the first sets up Proxmox nodes, the second runs `network_tuning` on both `proxmox_cluster` and `pbs_nodes` groups.
* SSH uses the agent selected by the user's SSH configuration. The Mac
  profiles configure 1Password when available, with `~/.ssh/cluster.pub`
  selecting the PVE/PBS key. The old `private_key_file` setting in `ansible.cfg` is commented out.

## Project Structure

* **`site.yml`**: The main entry point playbook. Orchestrates the execution of roles.
* **`inventory.yml`**: (Gitignored) Defines the Proxmox hosts (IPs, names). See `inventory.yml.example`.
* **`group_vars/proxmox_cluster.yml`**: (Gitignored) Cluster-wide configuration and secrets (often Vault-encrypted). See `group_vars/proxmox_cluster.yml.example`.
* **`host_vars/`**: (Gitignored) Per-host configuration (PBS namespaces, corosync, ZFS). See `host_vars/node.yml.example`.
* **`roles/`**: Contains the logic for specific tasks:
  * `configure_repos`: Sets up Proxmox repositories (disables enterprise, enables no-subscription).
  * `cluster_setup`: Creates or joins a Proxmox cluster.
  * `pbs_storage`: Retired guard. Terraform owns the PBS connection.
  * `manage_isos`: Retired guard. Terraform owns cached media.
  * `iptag`: Tags LXC containers with IPs in the Proxmox UI.
  * `download_templates`: Retired guard. Terraform owns pinned templates.
  * `apt_cacher_ng`: Configures an existing guest through node or direct SSH tasks.
  * `prowlarr`: Configures the existing Prowlarr LXC with a pinned, checksum-verified release.
  * `homebridge`: Configures the existing Homebridge LXC with a pinned Debian package.
  * `spoolman`: Configures the existing Spoolman LXC with pinned application and uv releases.
  * `bambuddy`: Configures the existing Bambuddy LXC with a pinned release.
  * `nexdeck`: Configures the existing NexDeck LXC with a pinned source release.
  * `gitea_mirror`: Configures the existing Gitea Mirror LXC with pinned application and Bun releases.
  * `seerr`: Configures the existing Seerr LXC with pinned application and pnpm releases.
  * `pocket_id`: Configures the existing Pocket ID LXC with a pinned release binary.
  * `vaultwarden`: Configures the existing Vaultwarden LXC from pinned source and web-vault releases.
  * `forgejo`: Configures the existing Forgejo LXC with a pinned release binary and strict upgrade guards.
  * `sonarr`: Configures the existing Sonarr LXC with a pinned, checksum-verified release.
  * `radarr`: Configures the existing Radarr LXC with a pinned, checksum-verified release.
  * `gatus`: Configures the existing Gatus LXC (uptime monitoring/status page), built from a pinned source tarball with a pinned Go toolchain.
  * `diun`: Configures the existing Diun image-update watcher LXC.
  * `centralized_logging`: Configures Loki/Grafana in an existing guest and deploys Alloy.
  * `tailscale_router`: Configures the existing Tailscale subnet-router LXC.
  * `update_all`: Updates Proxmox host nodes and LXC containers.
  * `lxc_auto_update`: Schedules guarded Debian LXC package updates.
  * `lxc_app_updates`: Schedules compatible stable application updates with fresh backups.
  * `update_reminder`: Installs per-node Discord package-update reminders.
  * `healthcheck_reminder`: Installs a cluster-master-only Discord alert for down nodes/guests.
  * `cleanup_storage`: Detects and optionally destroys stale ZFS datasets.
  * `pbs_restore`: Restores LXC containers from PBS backups.
  * `vm_deploy`: Retired entry point that directs provisioning to Terraform.
  * `network_tuning`: Configures storage VLAN and 10G TCP sysctl tuning.
* **`ansible.cfg`**: Project-specific Ansible configuration.

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
cp host_vars/node.yml.example host_vars/atlas.yml  # repeat for each node
```

## Architecture

### Inventory & Configuration Model

* **Inventory**: `inventory.yml` (gitignored) - Contains node addresses and network settings. Legacy VMID ranges do not provision guests.
* **Group Variables**: `group_vars/proxmox_cluster.yml` (gitignored, Ansible Vault encrypted) - Cluster-wide secrets and configuration.
* **Host Variables**: `host_vars/<nodename>.yml` (gitignored via `host_vars/*.yml` pattern) - Per-node corosync ring1 configuration, plus PBS identity on the cluster master.

**Critical**: Local inventory, group variables, and host variables are
gitignored; only their sanitized `.example` templates are tracked. Role
defaults may still contain non-secret environment-specific defaults such as
service health-check addresses, so review tracked defaults as well as the
local variable files before changing behavior.

### Role execution and infrastructure ownership

`site.yml` configures host repositories, optional cluster bootstrap, guest
software, updates, reminders, logging, and explicit recovery/cleanup work.
`iptag` remains enabled by default. Guest application roles remain opt-in.
Its second play applies network tuning to PVE and PBS hosts.

Terraform owns guest creation/hardware, backup jobs, HA policy, PBS storage
connection metadata, and image/template files. The four former Ansible roles
are removed from the active playbook. No Ansible site run may recreate those
owners or remove/re-add the PBS connection. Actual PBS host configuration,
users, datastores, and offsite backup scripts remain with their owning projects.

### Host Variables (per-node config)

Each node's `host_vars/<nodename>.yml` configures:

* `corosync_ring1_addr` — IP on the dedicated cluster sync network (10.10.50.x).

Legacy host variables can still contain `pbs_username` and `pbs_namespace`.
They no longer configure the cluster connection. Review that identity and
namespace in the ignored Terraform deployment instead.

### Security Model

1. **Ansible Vault**: Keep application credentials and webhooks in encrypted local variables. Terraform separately protects its PBS connection credential.
2. **Password Protection**: Tasks handling credentials must use `no_log: true` and must not place secrets in process arguments. Use a supported prompt, stdin, or secret-file mechanism.
3. **Gitignore Strategy**: `inventory.yml`, `group_vars/proxmox_cluster.yml`, and `host_vars/*.yml` are all gitignored to protect sensitive data. Their sanitized `*.yml.example` templates remain tracked.
4. **Installer Integrity**: Third-party releases and source revisions are pinned and checksum-verified before root executes or installs them. Bump versions and checksums together after reviewing upstream changes. The explicitly authorized `lxc_app_updates` workflow may select compatible stable releases automatically, resolve exact checksums or image digests, and deploy only after a fresh backup. Preserve its release, backup, health, and failed-retry guards.
5. **Transferred domain**: The user confirmed on 2026-11-01 that `meownow.app`
   was transferred and is no longer theirs. `s3.meownow.app` is retired locally.
   Its remaining public DNS and certificate administration belong to the current
   domain owner, not homelab maintenance. Do not treat historical records as
   authorization to manage that domain. See the certificate renewal notes in
   `README.md`.

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

# Inspect the resolved task list without changing hosts
ansible-playbook -i inventory.yml site.yml --list-tasks

# Dry run (check mode) with diff output
ansible-playbook -i inventory.yml site.yml --check --diff --ask-vault-pass
```

### Running Playbooks

```bash
# Full deployment (requires vault password)
ansible-playbook -i inventory.yml site.yml --ask-vault-pass

# Deploy to a single node
ansible-playbook -i inventory.yml site.yml --limit atlas --ask-vault-pass

# Configure repositories only
ansible-playbook -i inventory.yml site.yml --tags repos --ask-vault-pass

# Run specific roles on a specific node
ansible-playbook -i inventory.yml site.yml --limit atlas --tags "repos,update" -e run_updates=true --ask-vault-pass
```

### Tags for Granular Execution

* `repos`: Configure repositories only.
* `cluster`: Run cluster setup logic.
* `pbs` and `restore`: Explicit PBS recovery, gated by `restore_from_pbs`. These tags do not configure storage.
* `lxc_auto_update` and `lxc_app_updates`: Install the separately gated update services.
* `update`: Update nodes and LXC containers (requires `-e 'run_updates=true'`).
* `update_reminder`: Install per-node Discord package-update reminders.
* `healthcheck_reminder`: Install the cluster-master-only Discord down-node/guest alert.
* `gatus`: Configure Gatus in an existing LXC, gated by `install_gatus`.
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

See `README.md` for guest software, system updates, and PBS recovery commands.
Use `../terraform/README.md` for provisioning and media management.

## Adding New Nodes

1. **Update `inventory.yml`**: Add the node address, name, and reviewed network-tuning settings. Legacy VMID ranges no longer allocate guests.
2. **Create `host_vars/<nodename>.yml`**: Copy `host_vars/node.yml.example` and populate `corosync_ring1_addr`. Terraform owns PBS connection settings.
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

* Retired. Terraform owns the PVE-to-PBS storage connection. Never remove and re-add it through Ansible.

### pbs_backup_job

* Retired. Terraform owns backup jobs, schedules, selection, and retention. Preserve existing jobs during adoption.

### cluster_setup

* The `cluster_master_node` creates the cluster; other nodes join.
* Skipped by default unless `setup_cluster: true`.

### manage_isos

* Retired. Terraform owns media. Preserve existing files and require a reviewed versioned source/checksum for new images.

### apt_cacher_ng

* Manages Apt-Cacher NG with repository-owned Ansible tasks.
* Resolves an existing LXC by hostname, or configures an explicitly selected
  guest through `apt-cacher-ng-guests.yml`.
* Installs `apt-cacher-ng`, removes the legacy remote updater, configures HTTPS
  pass-through and the local APT proxy, and verifies the service. Only the
  node workflow installs `avahi-daemon`.
* Skipped by default unless `install_apt_cacher_ng: true`.

### Managed application LXCs

* Repository-owned application roles use the shared `tasks/create_lxc.yml`
  bootstrap for software only. Terraform provisions new containers. Preserve
  existing privilege modes and raw passthrough settings during adoption.
* Existing HA-managed containers are located at run time through
  `tasks/resolve_lxc_node.yml`. A role's `<role>_node` value is therefore the
  lookup fallback, not a reliable statement of its current location. It does
  not authorize creation when the guest is absent.
  Names, VMIDs, and fallback nodes documented below describe tracked defaults,
  not verified live state; inspect cluster resources before operational work.
* Preserve `tasks/service_directories.yml` and `files/service-directories.py`
  when preparing service-owned paths. They reject unsafe ancestors. Do not
  replace them with recursive root ownership or writes through application links.

### nexdeck

* The role installs `homelab.py` and a checked frontend patch after the pinned
  release. Revalidate both against the upstream adapter and renderer during upgrades.
* The combined map reads Proxmox, TrueNAS, and PBS. Dashboard links accept
  explicit HTTP(S) URLs without credentials. Do not derive links from app secrets.
* The editable Start board lives in the application database. The tracked
  `files/nexdeck/start-board.yml.example` is an import template, not desired state.
  Export the current board before edits. Preserve `/var/lib/nexdeck` and uploads.
* See `files/nexdeck/README.md` for editing, recovery, and guest-based tests.

### netdata

* Use the explicit `netdata.yml` inventory group. This standalone deployment is
  intentionally separate from `site.yml` and does not provision guests.
* Preserve pinned static artifacts, source ACLs, bounded retention, and the
  private streaming credential. Keep the TrueNAS collector separate from its
  appliance agent. See [Ask the lab](docs/netdata.md).
* Open WebUI owns the private OpenAI connection and native MCP tool allowlist.
  Preserve unrelated providers and tools. Never expose generic function
  execution, raw logs, or SSH credentials through this model.
* The optional native `homelab_repairs` tool stages plans. Its matching
  `homelab_repair_controls` Action uses owner-bound Review/Approve/Cancel buttons
  for each immutable app proposal. No model-visible approval tool exists.
  Bind each plan to its assistant message and compare the persisted and clicked
  exact review before approval. Do not restore popup callbacks or text approvals.
  Preserve exact field and destination allowlists, private backups, stale-state
  checks, single attempts, and verification. Chat text is not approval. Never turn this into an arbitrary
  shell, HTTP, Docker, or file-edit tool. See [approved repairs](docs/app-repairs.md).
  Seerr's `libraries` field is read-only. Library repairs require a fresh,
  verified complete catalog and exactly one old/new ID pair. Explicit approval
  covers a complete catalog sync followed by restoring the replacement's enabled
  selection. Show the lost scan marker and partial-failure risk. Unexpected
  catalogs stop the second write. Never retry or roll back automatically.
* `app-observer.yml` adds fixed app self-checks and filtered diagnostics. Preserve
  source allowlists, redaction, ingestion-time labels, and unknown/partial
  health states. Do not replace these with arbitrary URL, shell, or LogQL tools.
  See [application observations](docs/app-observer.md).
* Verify fresh measurements and an actual tool-assisted chat. Container resource
  metrics do not establish application health or update availability.

### centralized_logging

* Configure the existing logging guest and collectors. Loki queries stay on
  loopback. Port 3100 permits only push/readiness routes from reviewed sources.
* `centralized_logging_ingest_cidrs` requires explicit IPv4 `/32` sources.
  Update this policy for changed collector addresses. Discovery must not widen it.
* Preserve APT package pins/holds and isolated retention-test ports. See
  `README.md` and `tests/README.md` for configuration and boundary checks.

### prowlarr

* Manages Prowlarr with repository-owned Ansible tasks.
* The tracked defaults identify `prowlarr-nash` as VMID 104 with `atlas` as the lookup fallback; existing application data is preserved.
* Pins the Prowlarr release and checksum, manages dependencies, data directory, service, and health checks, and removes the remote updater.
* Skipped by default unless `install_prowlarr: true`.

### homebridge

* Manages Homebridge with repository-owned Ansible tasks.
* The tracked defaults identify `homebridge-nash` as VMID 105 with `prometheus` as the lookup fallback; existing data is preserved.
* Pins the Homebridge Debian package and checksum-verifies its repository key, manages the APT source and package pin, and removes the remote updater.
* Skipped by default unless `install_homebridge: true`.
* `homebridge-discovery.yml` separately publishes paired bridge metadata through
  the gateway's existing Avahi service. It is not part of `site.yml`.
  Keep only public advertisement metadata in its ignored inventory. Never copy
  pairing PINs or keys. Verify discovery from the client LAN and device control.

### spoolman

* Manages Spoolman with repository-owned Ansible tasks.
* The tracked defaults identify `spoolman-nash` as VMID 102 with `atlas` as the lookup fallback; its `.env` file and SQLite data directory are preserved.
* Pins and checksum-verifies both Spoolman and uv releases, builds dependencies before atomically swapping the application, removes the remote updater, and verifies the reported application version.
* Skipped by default unless `install_spoolman: true`.

### bambuddy

* Configures the existing guest selected by `bambuddy_hostname`. Terraform
  allocates its VMID. `bambuddy_node` is only the lookup fallback.
* Pins and checksum-verifies the Bambuddy source release, builds its Python and
  frontend dependencies inside the LXC, preserves an existing `.env`, manages
  the systemd service, and verifies the web service.
* Skipped by default unless `install_bambuddy: true`.

### gitea_mirror

* Manages Gitea Mirror with repository-owned Ansible tasks.
* The tracked defaults identify `git-mirror-nash` as VMID 119; its environment file and SQLite data directory are preserved, and `gitea_mirror_node` is only the lookup fallback.
* Pins and checksum-verifies both Gitea Mirror and Bun releases, refuses destructive 2.x migrations, checks SQLite integrity before upgrades, builds the new release before stopping the service, keeps a pre-upgrade backup, rolls back automatically when the upgraded service fails its health check, removes the remote updater, and verifies the installed version.
* Skipped by default unless `install_gitea_mirror: true`.

### seerr

* Manages Seerr with repository-owned Ansible tasks.
* The tracked role defaults identify `seerr-nash` as VMID 117; `/etc/seerr/seerr.conf` and SQLite config data are preserved. Local overrides may retain an older hostname, so resolve the configured hostname before acting.
* Pins and checksum-verifies both Seerr and pnpm releases, requires NodeSource Node.js 22, refuses to overwrite an unmigrated Overseerr install, checks SQLite integrity before upgrades, builds the new release before stopping the service, keeps a pre-upgrade backup, rolls back automatically when the upgraded service fails its health check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_seerr: true`.

### pocket_id

* Manages Pocket ID with repository-owned Ansible tasks.
* The tracked defaults identify `pocketid-nash` as VMID 100; its `.env` (including the mandatory encryption key) and SQLite data are preserved.
* Pins and checksum-verifies the single release binary, checks SQLite integrity before upgrades, backs up the binary, data, and environment before swapping, rolls back automatically (including the data directory, since new versions migrate the schema on start) when the upgraded service fails its health check, removes the remote updater, and verifies the binary-reported version.
* Skipped by default unless `install_pocket_id: true`.

### vaultwarden

* Manages Vaultwarden with repository-owned Ansible tasks based on the Community Scripts design; it never downloads or runs that installer.
* The tracked defaults identify `vaultwarden-nash` as VMID 125 with `atlas` as the lookup fallback. Vaultwarden, Rust, rustup, and the matching web vault are version- or checksum-pinned.
* Preserves and integrity-checks SQLite data, stages builds before stopping the service, keeps a pre-upgrade database/binary/web-vault backup, rolls back failed health checks, and runs under a hardened non-root systemd unit.
* Skipped by default unless `install_vaultwarden: true`.

### forgejo

* Manages Forgejo with repository-owned Ansible tasks.
* The tracked defaults identify `forgejo-nash` as VMID 103. The role preserves `app.ini` and all repository data; verify the live service endpoint and hosting node before operational work.
* Pins and checksum-verifies the release binary, refuses downgrades and skipped major versions (Forgejo must upgrade one major at a time), checks SQLite integrity before upgrades, stages and sanity-runs the new binary before stopping the service, backs up the binary, config, and database (not the multi-GB repositories, which upgrades never rewrite), rolls back binary, database, and config automatically when the upgraded service fails its health check, removes the remote updater, and verifies the binary-reported version.
* Skipped by default unless `install_forgejo: true`.

### sonarr

* Manages Sonarr with repository-owned Ansible tasks.
* The tracked defaults identify `sonarr-nash` as VMID 110; the role preserves `config.xml` and the SQLite databases, keeps the service running as the `media` user, and does not manage its in-container media mounts.
* Pins and checksum-verifies the release tarball, backs up config and databases before atomically swapping the install directory, rolls back automatically when the upgraded service fails its `/ping` check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_sonarr: true`.

### arr_storage.yml

* Standalone guest-targeted playbook; see `docs/arr-storage.md`.
* Orders ifupdown completion before network readiness, requires existing NFS
  mounts before Sonarr/Radarr, and retries failed starts with systemd timers.
* Separate from the application roles and `site.yml`. It does not reboot guests.
* Both guests passed explicit reboot verification on 2026-10-02.

### radarr

* Manages Radarr with repository-owned Ansible tasks.
* The tracked defaults identify `radarr-nash` as VMID 111 with `prometheus` as the lookup fallback; `config.xml` and the SQLite database are preserved, and the service runs as the `media` user.
* Pins and checksum-verifies the release tarball, backs up config and database state before atomically swapping the install directory, rolls back automatically when the upgraded service fails its `/ping` check, removes the remote updater, and verifies the API-reported version.
* Skipped by default unless `install_radarr: true`.

### gallery_dl (retired)

* The user confirmed retirement on 2026-10-24. The role remains as reference
  code only and is not imported by `site.yml`.
* The local active variables and tracked example no longer contain its enable
  flag or profiles. The old tag/enable flag cannot deploy it through `site.yml`.
* Do not reconnect it to active playbooks without an explicit new deployment
  request. Preserve existing data, backups, and the ignored cookies file.

### update_all

* Updates both Proxmox hosts and all running LXC containers.
* For each container: detects package manager (apt/apk) and updates OS packages.
* Never executes application-specific updater hooks. Managed releases change through explicit role pins or the guarded `lxc_app_updates` workflow.

### update_apps

* Installs a repository-owned replacement for the Community Scripts
  `update-apps.sh` orchestration script on each Proxmox node.
* Backs up and updates only running, tagged, unmanaged LXCs with an existing
  `/usr/bin/update`. Managed applications use explicit role pins or the guarded
  `lxc_app_updates` workflow.
* Never downloads or sources the upstream orchestration script at runtime.

### lxc_auto_update

* Installs a native systemd timer on each node for running Debian LXCs only.
* Requires a recent LXC backup before every update. Preserves APT holds and
  pins, refuses package removal, and never changes guest power or host packages.
* Opt in with `install_lxc_auto_update: true` and `lxc_auto_update_enabled: true`.
* Keep Terraform backup schedules and application release ownership intact.
* Compare failed systemd unit IDs across the package operation. Table padding
  or description changes must not count as a new failure. Keep the exact IDs
  in the private report and restrict brief output to reviewed unit names.
* Validate with `python3 tests/test_lxc_auto_update.py` and a live
  `lxc-auto-update --dry-run` on both nodes before enabling the timer.

### lxc_app_updates

* Runs weekly on each PVE node without a controller or Codex dependency.
* Selects stable releases within the installed major, or minor for 0.x.
  Rejects downgrades, prereleases, and releases younger than 72 hours.
* Creates a fresh PBS snapshot backup before each application deployment.
  Reuses managed roles or bounded native adapters. Never invokes remote hooks.
* Saves successful pins in `/etc/pve/priv/homelab-app-updates`. Shared bootstrap
  loads these pins during later ordinary role runs. Explicit extra vars win.
* Failed deployments require inspection and explicit `--retry-failed`.
  Preserve previous code, data, and backups. Never restore PBS automatically.
* Validate both Python test files, Ansible lint/syntax/check mode, and live
  `--dry-run` on both nodes before enabling `lxc-app-updates.timer`.
* SearXNG has no stable releases. Manual Minecraft packs, major upgrades,
  auxiliary database images, and build-tool upgrades remain separate work.
* Both update services share `files/lxc-update-notify.py` through systemd
  `ExecStopPost`. Preserve invocation-ID checks, credential redaction, and
  disabled mentions. The optional `lxc_update_discord_webhook_url` belongs in
  ignored variables or Vault. Test delivery without running guest updates.

### update_reminder

* Installs a systemd timer on every Proxmox node and checks the node plus its
  currently running LXCs for pending OS packages.
* Sends an independent Discord reminder only after a configurable package
  threshold, with a persistent cooldown to suppress repeated messages.
* Refreshes package metadata and simulates upgrades but never installs them.
* Stores the Vault-supplied webhook in a root-only environment file and keeps
  it out of logs and process arguments.
* Skipped by default unless `update_reminder_enabled: true`.

### healthcheck_reminder

* Installs a systemd timer on the cluster master node only; checks are
  cluster-wide via `pvesh get /cluster/resources`, so running it on every
  node would duplicate alerts.
* Flags any Proxmox node not `online` and any LXC/VM not `running`; guests
  can be excluded with `healthcheck_reminder_skip_vmids`.
* Re-notifies immediately if the set of down items changes, otherwise backs
  off for `healthcheck_reminder_repeat_after_minutes`.
* Stores the Vault-supplied webhook in a root-only environment file and keeps
  it out of logs and process arguments.
* Skipped by default unless `healthcheck_reminder_enabled: true`.

### gatus

* Configures existing `gatus-nash`. Gatus has no prebuilt binary releases, so
  the role builds it from a pinned, checksum-verified source tarball using a
  pinned, checksum-verified Go toolchain; Go additionally verifies every
  dependency against sum.golang.org during the build.
* Generates `config.yaml`: probes every Proxmox node (TCP 8006), the PBS
  server (TCP 8007), and every managed app LXC that already defines a
  `<role>_health_url` — extend via `gatus_extra_endpoints`.
* Skipped by default unless `install_gatus: true`.

### diun

* Configures existing `diun-nash` and installs a pinned, checksum-verified Diun
  release that posts image update notifications to Discord.
* Watches the static `diun_watch_images` list through Diun's file provider; it
  does not discover containers from Docker or another host at run time.
* Skipped by default unless `install_diun: true`.

### tailscale_router

* Configures the existing unprivileged `tailscale-router-nash` LXC, installs a
  pinned Tailscale package from a checksum-verified-key APT repository, and
  advertises the configured LAN routes.
* Requires existing `/dev/net/tun` passthrough. It fails when the expected
  device entries are absent. Terraform owns guest hardware and lifecycle.
* Keep `tailscale_router_auth_key` in Vault. At least one advertised CIDR is
  required, and new routes may still require approval in the Tailscale admin
  console unless the tailnet has matching `autoApprovers`.
* Skipped by default unless `install_tailscale_router: true`.

### pbs_restore

* Restores LXC containers from PBS.
* Runs on a single target node (`pbs_restore_node`). LXC and QEMU backups are supported.

### iptag

* Installs a repository-owned Python service that tags LXC containers and VMs with their IP addresses in the Proxmox UI.
* Enabled by default (`install_iptag: true`).
* Manages the runtime, configuration, manual `iptag-run` command, and systemd unit directly with Ansible.
* Migrates existing installs from `/lib/systemd/system/iptag.service` to an Ansible-managed unit in `/etc/systemd/system`.
* Configurable with `iptag_tag_format_choice`, `iptag_loop_interval`, `iptag_allowed_cidrs`, `iptag_debug`, and `iptag_command_timeout`.

### download_templates

* Retired. Terraform owns pinned template sources. Do not restore automatic latest-template selection here.

### cleanup_storage

* Reports stale/orphaned ZFS datasets.
* **Always dry-run by default**. Only destroys if `cleanup_storage_destroy_stale: true`.

### vm_deploy

* Retired. The role fails explicitly and directs operators to Terraform.
* The old VM creation task file was removed. Never reconnect provisioning here.

### macos.yml

* Retired creation entry point. It fails before any remote change.
* VM 108 was retired on 2026-10-29 through Terraform, together with its
  dedicated backup job. Preserve retained backups and original ISO files.
  A new macOS guest needs an explicit provisioning request.
* Installation notes remain in `docs/macos.md` as historical reference.

### network_tuning

* Runs as a separate play on both `proxmox_cluster` and `pbs_nodes`.
* Configures a VLAN subinterface and applies TCP sysctl tuning (e.g., BBR).

## Ansible Configuration (`ansible.cfg`)

* **Fact Caching**: Enabled with a 1-hour timeout.
* **Host Key Checking**: `StrictHostKeyChecking=accept-new` trusts a host on
  first use but rejects a changed key afterward.
* **SSH Pipelining**: Enabled for performance.
* **Privilege Escalation**: `become = true` is set globally.

### speedtest_tracker

* Deploys a digest-pinned LinuxServer Speedtest Tracker image through Docker
  Compose inside an unprivileged Debian 13 LXC. Uses the shared bootstrap.
* Opt in with `install_speedtest_tracker: true` and the `speedtest_tracker` tag.
* The initial fallback is Atlas, VMID 130. Verify live placement before operations.
* Secrets are generated inside the LXC and stored in a root-only file. Preserve
  `/opt/speedtest-tracker/secrets.env` with `/var/lib/speedtest-tracker` backups.
* Tests run hourly. A speed test can temporarily consume the Internet connection.

### homelable

* Deploys checksum-pinned Homelable source with Python and Caddy in an
  unprivileged Debian 13 LXC. Opt in with `install_homelable` and tag `homelable`.
* Tracked defaults: Atlas, VMID 131, VLAN 40, port 3000. Confirm live state.
* Preserve `/var/lib/homelable`, the backend `.env`, and the root-only bootstrap
  password. Existing different releases require a reviewed migration.
* Check mode skips container operations. Verify live API/login/database health
  and repeat-run idempotency before declaring a deployment complete.

### zipline

* Authenticated uploads with public root-level file URLs. Use the dashboard
  for large files so each chunk fits within the proxy request limit.
* Uses digest-pinned Zipline and PostgreSQL in an unprivileged LXC.
* The fallback is Prometheus, VMID 126. Confirm live and configured ID usage.
* Creates a private administrator before public exposure. Registration and
  invitations are disabled. Preserve `/var/lib/zipline` and `/opt/zipline`.
* Optional `zipline_manage_proxy` manages an isolated NPM configuration and
  requires the `homelab-zipline` certificate first. See `docs/zipline.md`.
* The Mac client and Automator action are under `files/zipline/`.
* Use native account **Viewing Files** settings for rich-card branding, title,
  and color. Preserve those database settings during application deployments.
  See `docs/zipline.md` for the configured fields.
* Preserve direct PNG and extensionless screenshot links when changing video
  previews. Test the public viewer metadata, thumbnail, and raw video ranges.
  For an opted-in Discord preview, also verify a complete download within ten seconds,
  seeking, and withdrawal. Shared publication waits for a ready RAM preview.
  Keep the preview catalog separate from secrets, preserve the RAM budget and
  disabled container swap. Clip count must not reduce encoding quality. Queue
  new previews at capacity. Test nested silent/non-MP4 inputs before changing
  the encoder or publisher.
* Honor `zipline_clips_start_timer: false` by disabling the publisher timer.
  Preserve existing records, originals, and RAM previews when publication stops.
* NAS clips require explicit placement in the SMB Shared tree. Mirror its visible
  folders, including empty ones, under the existing dashboard folder. Preserve the
  nested read-only NFS mount, Docker no-symlink-follow check, per-file settling
  and withdrawal. See `docs/zipline.md` before changing storage or the publisher.

### librespeed

* Guest-only role, invoked by `librespeed-guests.yml` after Terraform creates a
  Debian 13 guest. Do not add it to the node-targeted `site.yml`.
* Pins and checksum-verifies LibreSpeed, with native nginx and PHP FPM.
* Local tests disable telemetry, ISP lookup, compression, buffering, and
  bandwidth overhead compensation. Use the direct guest HTTP address.

### offsite observer

* The independent `homelab-offsite-observer` repository owns its installer and
  activation gates. Follow `docs/offsite-observer.md`; do not duplicate its role.
* Terraform owns the dedicated LXC and firewall. Use console administration,
  no nesting/devices/host mounts, and no inbound listener. Keep credentials private.
* For guest mount failures, inspect the host's AppArmor audit and follow the
  guest mount checks in the deployment guide. Verify the actual filesystems.
* Installation stays disabled. Provider tests and activation need their real
  configuration and authorization. Home-cluster placement is not an offsite vantage.

### Local DNS and private web services

* `local-services.yml` manages a separate NPM configuration with private-peer
  admission checks. Keep route data in ignored cluster variables. Never add
  duplicate UI-managed NPM hosts for these names.
* `files/local_dns.py` adds records through UniFi's integration API over SSH.
  It rejects conflicts and never deletes records. Keep API keys and the real
  DNS JSON outside Git. See `docs/local-services.md` for checks and recovery.
* LibreSpeed uses direct DNS rather than the proxy. LANCache must forward to
  the local resolver for private names to work on its clients.
* TrueNAS routes require `scheme: https` and `require_tls_upstream: true`.
  Validate DNS and TLS from each calling application, not only the browser.
  Keep proxy upstreams on infrastructure addresses to avoid a proxy loop.

### PXE network boot

* `pxe-guests.yml` configures the existing PXE guest with signed iPXE, TFTP,
  HTTP, and rsync. Terraform owns its ISO library, per-VM installer files, and
  disk capacity. Its optional proxy DHCP supplies boot information only.
  Preserve router lease allocation, disable guest packet forwarding, and keep
  the managed-shim marker and updater protection.
  See [network boot](docs/network-boot.md) and [Terraform](../terraform/README.md#pxe-service-and-library).
* `files/unifi_pxe.py` previews or partially updates DHCP boot settings through
  the UniFi controller API over verified SSH. It backs up before writing and
  checks complete readback. Keep the API key and deployment JSON outside Git.
* DHCP belongs to each subnet's actual router. Do not enable UniFi routing on
  an externally routed VLAN. Arista changes need explicit approval through its
  separate workflow. See `docs/network-boot.md` for verification and recovery.

## LANCache VM

Use the guest-only [SSD cache workflow](docs/lancache.md). Terraform owns both disks.
Keep game data separate from the backed-up dashboard and check ownership of
the service addresses before cutover.
Preserve upstream HTTP/1.1, range normalization, and the loopback-only connection
pool on both the local redirect hop and the CDN hop. Keep the short Steam RAM
buffer separate from the persistent cache keys.
Validate uncached downloads with fresh chunks from a verified wired client.
See the proxy regression test and configuration restart rules in that guide.
Keep scheduled prefills on the worker-only bridge. Keep its subnet filter on
the dashboard access log and retain Hidden rules for past worker downloads.
Use the manager's native scheduled prefill for selected-game updates. Preserve
its game selections, platform logins, and schedule state. Keep Steam, Epic, and
Riot worker images digest-pinned through the Compose environment. Use full
persistence for unattended sessions that must recover after a VM restart.
The Steam worker also has a checksum-pinned local build. Its serialized progress
callback reads the current byte counter to prevent stale parallel reports from
aborting a download. Preserve the regression test and common protocol validation.
The Epic worker has a checksum-pinned local build for the four-byte chunk-header
expansion. Keep its manifest hash verification and tests. The manager receives
the immutable local image ID. See the build tasks before changing this pin.
The dashboard frontend also has a pinned local build. Its shared credential
request prevents duplicate Steam mobile-confirmation replies from SignalR and
the form. Preserve rejection handling and the regression tests when updating it.
Validate manager/worker protocol compatibility together. The pinned manager
currently requires the upstream development build for protocol 2 workers.
Check a real dashboard sign-in after upgrades. Preserve the database command
timeout during bulk fills and keep the existing account and authentication mode.
Keep `worker-dns` on the worker bridge. It must return the bridge cache IP,
while public DNS returns the public cache IP. Test Epic and Riot resolution
as well as Steam's explicit cache override.
The manager owns these workers. Do not introduce a second scheduler or place
credentials and selected game IDs in tracked variables. See the automatic
update procedure in the same guide.
