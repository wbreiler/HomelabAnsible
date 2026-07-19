# MinecraftLXCAnsible

Automated Minecraft server provisioning and modpack update system for a Proxmox cluster.

## Repository Structure

```
MinecraftLXCAnsible/
├── update-script/                  # Modrinth update script (deployed to each server LXC)
│   ├── update-modpack.sh           # Main update script
│   ├── update.conf.example         # Config template (copy to /etc/minecraft/update.conf)
│   ├── minecraft-update.service    # Systemd service unit
│   └── minecraft-update.timer      # Systemd timer (nightly at 4AM)
│
└── ansible/                        # Ansible provisioning playbook
    ├── provision.yml               # Main playbook
    ├── servers.yml.example         # Copy to ignored servers.yml and customize
    ├── ansible.cfg
    ├── hosts.ini                   # Static inventory (localhost only)
    ├── vault.yml.example           # Vault structure example (copy → vault.yml, encrypt)
    ├── group_vars/all.yml.example  # Copy to ignored all.yml and customize
    └── roles/minecraft_server/     # Role applied to each new LXC
        ├── tasks/main.yml
        ├── tasks/set_java_version.yml
        ├── templates/              # Jinja2 templates for systemd units and configs
        └── vars/main.yml
```

## Deployment Order

### Step 1 — Prepare Ansible vault

```bash
cd ansible/
cp vault.yml.example vault.yml
# Edit vault.yml: fill in Proxmox API credentials and Discord webhook URLs
ansible-vault encrypt vault.yml
```

### Step 2 — Prepare local environment configuration

```bash
cp group_vars/all.yml.example group_vars/all.yml
cp servers.yml.example servers.yml
```

Edit `group_vars/all.yml` for the local Proxmox nodes, network, storage, and
template. Both generated files are ignored by Git.

### Step 3 — Define your servers

Edit `servers.yml`. Each entry creates one LXC and configures it:

| Field | Description |
|---|---|
| `hostname` | LXC hostname (Greek/mythology theme) |
| `vmid` | Proxmox VMID (must not conflict with existing VMs) |
| `node` | Proxmox node: `prometheus`, `atlas`, or `nyx` |
| `cores` / `memory` / `disk` | CPU cores, RAM in MB, disk in GB |
| `modpack_slug` | Modrinth project slug, or `"vanilla"` |
| `pack_name` | Human-friendly name for Discord notifications |
| `mc_version` | Minecraft version string (e.g. `"1.21.1"`) |
| `loader` | `"neoforge"`, `"forge"`, `"fabric"`, `"quilt"`, or `""` for vanilla |
| `instance_name` | Systemd instance name (short, no spaces) |
| `discord_webhook_url` | References a vault variable |
| `xmx` / `xms` | JVM heap max / initial (e.g. `"6G"`, `"2G"`) |

> **VMID 300 is reserved** — DiscoPanel on Prometheus. Start new VMIDs at 301+.

### Step 4 — Run the playbook

```bash
cd ansible/
ansible-playbook provision.yml --ask-vault-pass
```

The playbook:
1. Creates each LXC via the Proxmox API (`community.proxmox.proxmox`)
2. Waits for SSH to become available
3. Applies the `minecraft_server` role to each new LXC
4. Creates or updates the `Minecraft Server Backups` cluster backup job on Proxmox (hourly, storage: `mnemosyne`) — adds provisioned VMIDs to the job, creating it if it doesn't exist

> **Container type: Unprivileged** with `nesting=1`. Minecraft server LXCs don't need host mounts, so unprivileged is correct and is set automatically by the playbook.

**To provision a single server** from the list:
```bash
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass -e server_filter=yabu-nash'
```

**To set timezone only** (skips provisioning, uses `--tags timezone`):
```bash
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass --tags timezone'
```

## Java Version Selection

The playbook automatically picks the correct Java version:

| Minecraft Version | Java | Distribution |
|---|---|---|
| 26.x+ (year-based) | 25 | GraalVM CE 25 |
| 1.21+ or 1.20.5+ | 21 | GraalVM CE 21 |
| 1.18 – 1.20.4 | 17 | Temurin 17 |
| 1.17 and below | 8 | OpenJDK 8 |

## Modpack Update Script

Each provisioned server gets `update-modpack.sh` at `/usr/local/bin/` and a nightly systemd timer.

**Manual run:**
```bash
update-modpack.sh                    # apply updates if available
update-modpack.sh --dry-run          # check only, no changes
update-modpack.sh --config /path/to/alternate.conf
```

**Config** (`/etc/minecraft/update.conf`):
```bash
MODPACK_SLUG="all-the-mods-9"
PACK_NAME="All the Mods 9"
MC_VERSION="1.21.1"
LOADER="neoforge"
INSTANCE_NAME="atm9"
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
MINECRAFT_DIR="/opt/minecraft"
```

**Update flow:** Discord announce → 5-min countdown → download, stage, and
validate required content while the server stays online → briefly stop the
service → atomically swap the staged content → restart and verify. Failures
after the swap restore the previous mod directory and restart the service.
The latest three backups are retained.

Logs: `/var/log/minecraft-update.log` (auto-rotates at 10 MB)

## Prerequisites

**Control machine:**
```bash
cd ansible/
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
```

**Proxmox nodes:**
- Debian 13 LXC template downloaded: `pveam download local debian-13-standard_13.1-2_amd64.tar.zst`
- SSH accessible as root from control machine
- API user with `PVEAdmin` role (or `root@pam`)

**Each server LXC** (handled automatically by playbook):
- `jq`, `curl`, `unzip`, `openjdk-XX-jre-headless`

## Network Details

| Resource | Address |
|---|---|
| Apt cache | `10.10.40.175:3142` (VLAN 40) |
| Guest network | `10.10.40.0/24` (VLAN 40, bridge `vmbr0`) |

## Adding a New Server

1. Add an entry to `ansible/servers.yml`
2. If it needs a new Discord webhook, add `vault_discord_webhook_<name>` to `vault.yml` and re-encrypt
3. Run `ansible-playbook provision.yml --ask-vault-pass`
