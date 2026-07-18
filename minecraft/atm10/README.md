# All the Mods 10 — Server

**Hostname:** atm10-nash  
**IP:** 10.10.40.150  
**Minecraft:** 1.21.1 (NeoForge)  
**CurseForge project:** [All the Mods 10](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10) (ID: 925200)  
**Proxmox VMID:** 304 (node: nash)  
**Java:** OpenJDK 21.0.11 (from Debian 13 repos)  
**NeoForge:** 21.1.228

## Directory layout (on the server)

```
/opt/minecraft/           # Server root (owned by minecraft:minecraft)
│   mods/                 # NeoForge mods
│   world/                # World data
│   backups/              # Rolling mod backups (last 3 kept)
│   .current_version      # CurseForge file ID of installed version
│   eula.txt
│   server.properties
│   libraries/            # NeoForge libraries (from installer)
│   ...

/etc/minecraft/
│   atm10.conf            # API key + Discord webhook (root:minecraft 640)
│   atm10.env             # JVM heap (XMX / XMS)

/usr/local/bin/
│   atm10-update.sh       # Nightly update script

/etc/systemd/system/
│   minecraft@atm10.service
│   minecraft-update.service
│   minecraft-update.timer
```

## Repository layout (this folder)

```
atm10/
├── README.md             # This file
├── setup.sh              # One-shot bootstrap (run on a fresh Debian 13 LXC)
├── update.sh             # Modpack update script (deployed as atm10-update.sh)
├── server.properties     # Reference copy of the server config
├── atm10.env.example     # JVM heap config template
└── systemd/
    ├── minecraft@atm10.service   # Systemd service unit
    ├── minecraft-update.service  # Update oneshot service
    └── minecraft-update.timer    # Nightly timer (04:00, Persistent=true)
```

## Initial setup

### Prerequisites

- Fresh Debian 13 LXC with internet access
- A CurseForge API key (free at [console.curseforge.com](https://console.curseforge.com))
- SSH access as root

### 1 — Write the config

SSH into the LXC and create `/etc/minecraft/atm10.conf`:

```bash
mkdir -p /etc/minecraft
cat > /etc/minecraft/atm10.conf << 'EOF'
CURSEFORGE_API_KEY='your-key-here'
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...   # optional
EOF
chmod 640 /etc/minecraft/atm10.conf
chown root:minecraft /etc/minecraft/atm10.conf 2>/dev/null || true
```

> **Note:** The CurseForge API key starts with `$2a$10$`. Always wrap it in **single quotes** in shell files — the `$` characters will be mangled by bash variable expansion otherwise.

### 2 — Run setup.sh

Clone this repo (or copy the `atm10/` folder) onto the LXC, then:

```bash
bash atm10/setup.sh
```

`setup.sh` will:
1. Install `openjdk-21-jre-headless`, `curl`, `jq`, `unzip`
2. Create the `minecraft` system user and `/opt/minecraft` directories
3. Download the latest ATM10 server pack from CurseForge
4. Extract the pack and run the NeoForge installer
5. Accept the Minecraft EULA
6. Write `server.properties` and `/etc/minecraft/atm10.env`
7. Deploy and enable the systemd units
8. Start the server

## Day-to-day operation

```bash
# Follow live server log
journalctl -fu minecraft@atm10

# Stop / start / restart
systemctl stop  minecraft@atm10
systemctl start minecraft@atm10

# Check update timer status
systemctl list-timers minecraft-update.timer

# Manually run the update check (dry-run)
atm10-update.sh --dry-run

# Manually apply an update immediately (no 5-min wait)
atm10-update.sh --no-wait
```

## Modpack updates

The `minecraft-update.timer` fires at **04:00 every night** (`Persistent=true`, so it catches up if the server was off).

When an update is available the script:
1. Posts a Discord warning (if webhook is set)
2. Waits 5 minutes
3. Stops `minecraft@atm10.service`
4. Backs up the current `mods/` directory (keeps last 3)
5. Downloads the new server pack from CurseForge
6. Extracts new mods
7. Restarts the service
8. Posts a Discord success message

Logs: `/var/log/atm10-update.log`

## JVM tuning

Edit `/etc/minecraft/atm10.env` on the server:

```bash
XMX=10G
XMS=4G
```

The server has **16 GB RAM**. ATM10 is a heavy modpack — `10G`/`4G` leaves headroom for the OS. Raise `XMX` if you consistently see GC pressure in the logs.

After editing, restart the service:

```bash
systemctl restart minecraft@atm10
```

## server.properties

Key settings for ATM10:

| Setting | Value | Reason |
|---|---|---|
| `allow-flight=true` | true | Many ATM10 mods trigger false-positive flight kicks |
| `enforce-secure-profile=false` | false | Allows offline-mode / cracked accounts if needed |
| `spawn-protection=0` | 0 | Lets players build at spawn |
| `online-mode=true` | true | Require valid Minecraft accounts |

Full reference copy is at `atm10/server.properties` in this repo.

## Hardware

| Resource | Allocation |
|---|---|
| RAM | 16 GB |
| CPU | 4 cores |
| Disk | 128 GB (ZFS, on Proxmox node nash) |
| Network | VLAN 40 — 10.10.40.150 |
| Java | OpenJDK 21.0.11 |

## What was done (initial setup — 2026-05-17)

1. Fresh Debian 13 LXC (VMID 304 on nash), 16 GB RAM / 4 cores / 128 GB disk
2. Installed `openjdk-21-jre-headless`, `curl`, `jq`, `unzip` via apt
3. Created `minecraft` system user (UID 999), `/opt/minecraft`, `/etc/minecraft`
4. Downloaded ATM10 7.0 server pack (`ServerFiles-7.0.zip`) from CurseForge via API
5. Extracted server pack contents to `/opt/minecraft`
6. Ran the bundled NeoForge installer (`neoforge-21.1.228-installer.jar --installServer`)
7. Wrote `eula.txt`, `server.properties`, `/etc/minecraft/atm10.env`
8. Deployed systemd units and enabled `minecraft@atm10.service` + `minecraft-update.timer`
