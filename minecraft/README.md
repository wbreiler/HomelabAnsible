# Minecraft server automation

This project provisions unprivileged Minecraft LXCs on Proxmox and reconciles
already-running servers. It supports Modrinth, CurseForge, and manually supplied
official server packs.

## Layout

- `ansible/provision.yml` creates and starts LXCs, reconciles HA placement,
  configures new guests, and merges their VMIDs into the cluster backup job.
- `ansible/site.yml` configures existing guests from their `ansible_host` values;
  it does not create, move, resize, start, or stop LXCs or alter backup jobs.
- `ansible/ha.yml` reconciles only PVE 9 HA resources and node-affinity rules.
- `update-script/update-modpack.sh` is deployed to automatically managed guests.
- `update-script/apply-manual-pack.sh` deploys official server-pack ZIP or
  Modrinth `.mrpack` files from the controller.

Run Ansible commands from `minecraft/ansible/` so its `ansible.cfg`, inventory,
and relative paths apply.

## Local setup

```bash
cd minecraft/ansible
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
cp group_vars/all.yml.example group_vars/all.yml
cp servers.yml.example servers.yml
cp vault.yml.example vault.yml
ansible-vault encrypt vault.yml
```

Customize the two ignored YAML files. `group_vars/all.yml` holds local Proxmox,
storage, bridge, VLAN, and node settings. `servers.yml` holds guest addresses and
desired server state. Put API credentials, the SSH public key, CurseForge key,
and Discord webhooks in the ignored encrypted `vault.yml`; preserve the
CurseForge key literally because its `$2a$10$` prefix is shell-sensitive.

The controller needs Ansible, the Python requirements, the collection in
`requirements.yml`, and SSH access appropriate to the selected entry point.
Provisioning expects the configured Debian 13 template/storage to be available
to Proxmox; the playbook ensures the named template exists on target nodes.

## Define servers

Start from `ansible/servers.yml.example`, which is the authoritative variable
example. Important fields include:

| Field | Purpose |
| --- | --- |
| `hostname`, `ansible_host`, `vmid`, `node` | Guest identity, existing address, and Proxmox placement |
| `cores`, `memory`, `disk` | LXC resources used during provisioning |
| `pack_source` | `modrinth`, `curseforge`, or `manual` |
| `modpack_slug`, `curseforge_project_id` | Upstream pack identity |
| `mc_version`, `loader`, `loader_version` | Minecraft and loader selection |
| `instance_name`, `xms`, `xmx` | systemd instance and JVM heap |
| `server_properties`, `ops` | Managed server settings and operators |
| `ha_*` | Optional HA resource and node-affinity policy |
| `extra_modrinth_mods` | Extra Modrinth projects layered onto an automatic pack |
| `bluemap_*`, `dh_pregen_*`, `chunky_pregen_*` | Optional idle-only map/world generation |

Check live cluster state and the ignored `servers.yml`, then allocate the next
unused sequential VMID without arbitrary reservations or gaps. Provisioned
Minecraft LXCs are unprivileged and use `nesting=1`.

## Reconcile existing servers

```bash
cd minecraft/ansible
ansible-playbook site.yml --ask-vault-pass --check --diff
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --ask-vault-pass -e server_filter=yabu-nash
```

`site.yml` validates that selected addresses are unique VLAN 40 addresses and
configures guests serially. Check mode is a dry run, not runtime verification.

## Provision LXCs

```bash
cd minecraft/ansible
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass'
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass -e server_filter=yabu-nash'
```

The SSH-agent wrapper is required when any selected server uses `migrate_from`,
because delegated migration needs the key on its second SSH hop. Provisioning
creates/starts guests, discovers their DHCP addresses, waits for SSH, configures
them, and then updates the backup job whose comment is exactly
`Minecraft Server Backups`. A new job is hourly, snapshot mode, zstd-compressed,
and uses `proxmox_backup_storage`; an existing job keeps its storage, schedule,
mode, compression, comment, and enabled state while receiving the new VMIDs.

Do not use `provision.yml --tags timezone` as a guest-only shortcut: tasks tagged
`always` still perform Proxmox/API discovery and guest inventory construction.
Use `site.yml --tags timezone` for an existing server.

## HA placement

```bash
cd minecraft/ansible
ansible-playbook ha.yml --ask-vault-pass -e server_filter=atm10-nash
```

Set `ha_enabled: true`, list preferred/fallback nodes in `ha_nodes`, and use
`ha_strict: true` to forbid unlisted nodes. `ha_auto_rebalance: false` blocks
routine balancing moves, while `ha_failback: false` leaves a failed-over guest
in place. A PVE 9 resource can belong to only one node-affinity rule. For an
intentional split from a shared rule, set `ha_detach_from_rule`; the playbook
preserves other members and uses the API digest guard.

## Pack management

For Modrinth and CurseForge sources, the role deploys
`/usr/local/bin/update-modpack.sh`, its config under `/etc/minecraft/`, and a
nightly persistent timer at 4 AM. The updater stages and validates content while
the server remains online, announces/counts down, briefly stops the service,
swaps content, verifies restart, and rolls back on failure. `--no-wait` is used
during initial provisioning. Manual invocations support `--dry-run`, `--no-wait`,
and `--config PATH`; logs are written to `/var/log/minecraft-update.log` and the
latest three backups are retained.

`extra_modrinth_mods` can layer standalone Modrinth releases onto either kind of
automatically managed pack. It does not apply to `pack_source: manual`.

For a broken auto-reconstructed pack, prefer the official server pack:

1. Set `pack_source: manual` and the exact Forge/NeoForge `loader_version`.
2. Run `minecraft/update-script/apply-manual-pack.sh PACK.zip root@HOST` or pass
   a `.mrpack`. The latter is assembled from `modrinth.index.json` plus its
   overrides before deployment.
3. Reconcile the guest with `site.yml -e server_filter=HOSTNAME`.

Manual mode disables/removes the automatic update timer. The deployment script
backs up existing `mods`, `config`, `defaultconfigs`, and `kubejs`, then deploys
fresh content (including KubeJS scripts/data/assets and world datapacks).
If `run.sh` already exists, reconciliation
does not verify its loader version, so replace or verify loader files when the
version changes.

## Runtime features

The role manages `minecraft@.service` and per-instance environment files.
Minecraft version selects Java automatically: Java 25/GraalVM CE for year-based
26.x+, Java 21/GraalVM CE for 1.20.5+, Java 17/Temurin for 1.18-1.20.4, and
Java 8/OpenJDK for 1.17 and older.

Optional BlueMap, Distant Horizons, and Chunky controllers use an LXC-local RCON
password, pause while players are online, and resume while empty. Distant
Horizons supports a one-time `dh_pregen_followup_radius` expansion. See
`servers.yml.example` for their complete settings and disabled defaults.

External DNS SRV records and router port forwards are managed outside this
repository. See `AGENTS.md` for the last documented assignments, and verify
those external systems live before relying on them.

## Validation

```bash
cd minecraft/ansible
ansible-lint
ansible-playbook site.yml --syntax-check --ask-vault-pass
bash -n ../update-script/update-modpack.sh ../update-script/apply-manual-pack.sh
python3 ../update-script/test_apply_manual_pack.py
```

Syntax/lint checks do not prove live convergence or service health.
