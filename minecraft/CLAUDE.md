# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo does

Automates Minecraft server provisioning and modpack updates for a Proxmox cluster (`cluster-nash`, nodes: Prometheus, Atlas, Nyx). Two independent components:

1. **`update-script/`** — Modpack update script deployed to each Minecraft server LXC
2. **`ansible/`** — Playbooks that manage HA placement, create LXCs via the Proxmox API, then SSH in to configure them

These components are not coupled at the code level — they share conventions (paths, config format) but run independently on different machines.

## Network layout

| Resource | Address |
|---|---|
| apt-cacher-ng proxy | `10.10.40.175:3142` (VLAN 40) |
| Proxmox API | `10.10.30.2` (cluster VIP, in vault) |

## Key constraints

- **Minecraft server LXCs are unprivileged** with `nesting=1` (set by playbook automatically).
- **VMID 300 is reserved** (DiscoPanel on Prometheus). Allocate the next unused
  sequential VMID in the 100 range after checking live cluster state; do not
  jump to 301+.
- The CurseForge API key starts with `$2a$10$` — always store/echo it in **single quotes** to prevent bash variable expansion mangling it.

## Shell scripts (`set -euo pipefail` conventions)

Both bash scripts use `set -euo pipefail`. Two patterns that matter:

- **Arithmetic in conditions**: use `if (( expr )); then` — never `(( expr )) && cmd` or `(( expr )) || cmd`, because arithmetic expressions return exit 1 when false and trigger `set -e`.
- **Functions called inside `$()`**: any `log()` call (which echoes to stdout) inside a command substitution will corrupt the captured value. Functions called inside `$()` must write only to stderr.

## Ansible

Run from `ansible/`:

```bash
# Reconcile existing servers only (no Proxmox mutations)
ansible-playbook site.yml --ask-vault-pass --check --diff

# Provision all servers (spawns a fresh SSH agent so ForwardAgent works for migration rsync)
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass'

# Provision a single server
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass -e server_filter=cobbleverse-nash'
```

The `ssh-agent bash -c '...'` wrapper is required whenever any server has `migrate_from` defined. The migration rsync delegates to the source host and SSHes onward to the new LXC; without an agent carrying `lxc_nash`, that second hop fails with publickey denied.

**Two-play architecture**: Play 1 runs on `localhost` against the Proxmox API to create LXCs and waits for SSH. Play 2 runs on the `newly_provisioned` dynamic group (populated by `add_host`) to apply the `minecraft_server` role. Re-running is idempotent.

**Existing-server entrypoint**: `site.yml` builds an in-memory inventory from
the `ansible_host` values in ignored `servers.yml`, then applies the role with
`serial: 1`. It never creates, moves, resizes, starts, or stops LXCs through
Proxmox and does not modify cluster backup jobs.

**HA-only entrypoint**: `ha.yml` reconciles PVE 9 HA resources and node-affinity
rules from each server's optional `ha_*` values. It does not provision or
configure guests. `ha_auto_rebalance: false` blocks routine balancing moves;
`ha_failback: false` leaves a failed-over server in place until an operator
manually returns it to its preferred node.

**Vault setup**: `cp vault.yml.example vault.yml`, fill in values, `ansible-vault encrypt vault.yml`. The file `vault.yml` is gitignored.

**Local configuration setup**: Copy `group_vars/all.yml.example` to
`group_vars/all.yml` and `servers.yml.example` to `servers.yml`. The generated
files are gitignored so node addresses, storage names, VMIDs, operators, and
migration paths remain local.

**Adding a server**: Edit the ignored `servers.yml`. For CurseForge packs add `pack_source: curseforge` and `curseforge_project_id: "NNNNNN"`. The numeric project ID is in the URL on curseforge.com.

**`pack_source: manual` — recommended fallback for broken auto-fetched packs**: Some CurseForge/Modrinth-side reconstructions of a modpack (via `update-modpack.sh`'s API-driven fetch) can differ subtly from the pack's official server-pack download — e.g. mismatched mod jar builds — in ways that cause runtime bugs the auto-fetch path can't detect (a client "Connection Lost" `ResourceLocationException` on `bettermc-nash`/`bettermc2-nash` traced back to exactly this: the auto-fetched mod set corrupted a large network sync packet; rebuilding from the official ServerPackCreator/CurseForge server-pack zip fixed it immediately). When a pack is misbehaving and the cause isn't an obvious single-mod config issue, prefer recreating from the official server pack over continuing to debug the auto-fetched version:

1. Get the official server pack onto the controller (e.g. `~/Downloads/<name>.zip` or `.mrpack`) — either a CurseForge/ServerPackCreator-style zip (mods/config/etc. at the zip root) or a Modrinth `.mrpack` file.
2. Set `pack_source: "manual"` on the server entry. For CurseForge-style zips also add `loader_version: "X.Y.Z"` (check `variables.txt`/`manifest.json` in the zip); for `.mrpack` files the exact loader version is read from `modrinth.index.json`'s `dependencies` automatically by the script in step 3 — set `loader_version` in `servers.yml` to match what it reports. This disables `update-modpack.sh` entirely for that server: no auto-fetch during provisioning, and `minecraft-update.timer` is not deployed (or is disabled if converting an existing server).
3. Run `minecraft/update-script/apply-manual-pack.sh <path-to-zip-or-mrpack> root@<ansible_host>`. It runs on the controller (not the LXC), detects the format, and for `.mrpack` assembles a full server pack first — downloading each server-required file from `modrinth.index.json` and layering `overrides/` then `server-overrides/` on top — before deploying the same way as a plain zip: stops the service, backs up the existing `mods/`, `config/`, `defaultconfigs/` (e.g. `mods.pre-zip-recreate.<timestamp>`, never deleted outright), and rsyncs the fresh `mods/`, `config/`, `defaultconfigs/`, `datapacks/` (→ remote `world/datapacks/`) into `/opt/minecraft`.
4. Run `site.yml` (`-e server_filter=<hostname>`) to reconcile everything else (JVM env, systemd unit, server.properties, timer state). If `run.sh` is already present with the matching loader version, the role skips reinstalling it; if not, a "manual pack" task section installs Forge/NeoForge via the official installer using `loader_version`.

A server on `pack_source: manual` gets no further automatic mod updates — updating it means repeating this process with a newer server pack.

**Extra mods on top of a modpack**: Add `extra_modrinth_mods: ["slug", ...]` to a server entry to layer standalone Modrinth mods onto a pack that doesn't bundle them (works with either `pack_source`). `update-modpack.sh` resolves each slug to its latest release for the server's `MC_VERSION`/`LOADER` and installs it alongside the pack's mods. The resolved versions are recorded in `.current_extra_mods` (parallel to `.current_excludes`) so a change to the list, or a new upstream release of one of these mods, triggers a reinstall even when the pack version itself is unchanged.

**HA placement**: Set `ha_enabled: true`, list preferred and fallback nodes in
`ha_nodes` with priorities, and keep `ha_strict: true` to prevent placement on
unlisted nodes. PVE 9 permits each HA resource in only one node-affinity rule;
the playbook refuses to overwrite a conflicting rule. For an intentional split
from an existing shared rule, set `ha_detach_from_rule`; the playbook preserves
the other resources and supplies the rule digest to prevent concurrent writes.

**server.properties overrides**: Add a `server_properties:` block to any server entry. Keys use underscores (`spawn_protection`, `allow_flight`, `online_mode`, etc.) — the template converts them to hyphenated Minecraft format. Omitted keys use vanilla defaults. Re-running the playbook rewrites the file.

**Ops**: Add an `ops:` list of Minecraft usernames to any server entry. The playbook looks up each UUID from the Mojang API (`api.mojang.com`) and writes `ops.json`. Players not found (404) are silently skipped. Ops are only written if the list is non-empty; servers without an `ops:` key get no ops.json.

**Java version** is auto-selected by `tasks/set_java_version.yml`: Java 25 / GraalVM CE 25 (MC 26.x+, year-based versioning), Java 21 / GraalVM CE 21 (MC 1.21+ or 1.20.5+), Java 17 / Temurin (1.18–1.20.4), Java 8 / OpenJDK (1.17 and below). MC version major > 1 always maps to Java 25.

**CurseForge provisioning** in the role delegates to `update-modpack.sh --no-wait` rather than reimplementing the API logic. The script and its config are deployed in step 5 (before the download steps) for this reason.

**Backup job**: At the end of Play 1, the playbook creates or updates a Proxmox cluster backup job (comment: `Minecraft Server Backups`, schedule: `0 * * * *`, storage: `mnemosyne`, mode: snapshot, compress: zstd). If the job already exists it merges the provisioned VMIDs into the existing VMID list. Identified by the comment string — don't rename it in the Proxmox UI. `proxmox_backup_storage` in `group_vars/all.yml` controls the target storage.

## External connectivity (`*.mc.wbreiler.com`)

Friends connect to `<name>.mc.wbreiler.com` with no port suffix. This works via
a Minecraft SRV record per server, managed in Cloudflare DNS (not part of this
repo — `wbreiler.com` uses Cloudflare nameservers, but there is no Cloudflare
API automation here; records are created by hand in the dashboard):

```
Name:     _minecraft._tcp.<name>.mc
Type:     SRV
Priority: 0
Weight:   0
Port:     <external_port>
Target:   mc.wbreiler.com
```

`mc.wbreiler.com` itself is a plain `A` record pointing at the home WAN IP.
There is no wildcard record and no per-subdomain `A`/`CNAME` — only the SRV
record resolves `<name>.mc.wbreiler.com`, which is why a plain `dig A` for a
server's subdomain returns nothing even when it's reachable in-game.

The router (outside this repo — not Ansible-managed) forwards
`WAN:<external_port>` → the server LXC's `ansible_host:25565`. Each externally
reachable server needs a unique external port both forwarded on the router
and published in its SRV record.

Current known assignments (from live DNS, not tracked anywhere else — update
this table by hand when ports change):

| Server | Subdomain | External port |
|---|---|---|
| cobbleverse-nash | cobbleverse.mc.wbreiler.com | 25565 |
| yabu-nash | yabu.mc.wbreiler.com | 25566 |
| homestead-nash | homestead.mc.wbreiler.com | 25569 |
| atm10-nash | atm10.mc.wbreiler.com | 6767 (legacy, inherited from the pre-migration DiscoPanel setup) |
| bettermc-nash | bmc.mc.wbreiler.com | 25567 |

## Modpack update script (`update-modpack.sh`)

Deployed to each server LXC at `/usr/local/bin/update-modpack.sh`. Config at `/etc/minecraft/update.conf`.

Flow: Discord announce → 5-min countdown (skipped with `--no-wait`) →
download, stage, and validate required content while the server stays online →
briefly stop the service → atomically swap the staged content → restart and
verify that it remains active, rolling back the mod directory and service on
failure. The updater records the version successfully started in
`/opt/minecraft/.running_version`; if the installed and running markers differ,
the next update check performs one corrective restart. The latest three backups
are retained.

`--no-wait` is used by the Ansible role for initial provisioning.

## Systemd on server LXCs

Uses a template unit `minecraft@.service` with `EnvironmentFile=/etc/minecraft/%i.env` for per-instance JVM heap. Start/stop a server: `systemctl start minecraft@<instance_name>`. Updates run nightly via `minecraft-update.timer` (4AM, `Persistent=true`).
