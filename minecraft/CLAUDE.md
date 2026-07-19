# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo does

Automates Minecraft server provisioning and modpack updates for a Proxmox cluster (`cluster-nash`, nodes: Prometheus, Atlas, Nyx). Two independent components:

1. **`update-script/`** — Modpack update script deployed to each Minecraft server LXC
2. **`ansible/`** — Playbook that creates LXCs via the Proxmox API, then SSHs in to configure them

These components are not coupled at the code level — they share conventions (paths, config format) but run independently on different machines.

## Network layout

| Resource | Address |
|---|---|
| apt-cacher-ng proxy | `10.10.40.175:3142` (VLAN 40) |
| Proxmox API | `10.10.30.2` (cluster VIP, in vault) |

## Key constraints

- **Minecraft server LXCs are unprivileged** with `nesting=1` (set by playbook automatically).
- **VMID 300 is reserved** (DiscoPanel on Prometheus). New servers start at 301+.
- The CurseForge API key starts with `$2a$10$` — always store/echo it in **single quotes** to prevent bash variable expansion mangling it.

## Shell scripts (`set -euo pipefail` conventions)

Both bash scripts use `set -euo pipefail`. Two patterns that matter:

- **Arithmetic in conditions**: use `if (( expr )); then` — never `(( expr )) && cmd` or `(( expr )) || cmd`, because arithmetic expressions return exit 1 when false and trigger `set -e`.
- **Functions called inside `$()`**: any `log()` call (which echoes to stdout) inside a command substitution will corrupt the captured value. Functions called inside `$()` must write only to stderr.

## Ansible

Run from `ansible/`:

```bash
# Provision all servers (spawns a fresh SSH agent so ForwardAgent works for migration rsync)
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass'

# Provision a single server
ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass -e server_filter=cobbleverse-nash'
```

The `ssh-agent bash -c '...'` wrapper is required whenever any server has `migrate_from` defined. The migration rsync delegates to the source host and SSHes onward to the new LXC; without an agent carrying `lxc_nash`, that second hop fails with publickey denied.

**Two-play architecture**: Play 1 runs on `localhost` against the Proxmox API to create LXCs and waits for SSH. Play 2 runs on the `newly_provisioned` dynamic group (populated by `add_host`) to apply the `minecraft_server` role. Re-running is idempotent.

**Vault setup**: `cp vault.example.yml vault.yml`, fill in values, `ansible-vault encrypt vault.yml`. The file `vault.yml` is gitignored.

**Local configuration setup**: Copy `group_vars/all.yml.example` to
`group_vars/all.yml` and `servers.yml.example` to `servers.yml`. The generated
files are gitignored so node addresses, storage names, VMIDs, operators, and
migration paths remain local.

**Adding a server**: Edit the ignored `servers.yml`. For CurseForge packs add `pack_source: curseforge` and `curseforge_project_id: "NNNNNN"`. The numeric project ID is in the URL on curseforge.com.

**server.properties overrides**: Add a `server_properties:` block to any server entry. Keys use underscores (`spawn_protection`, `allow_flight`, `online_mode`, etc.) — the template converts them to hyphenated Minecraft format. Omitted keys use vanilla defaults. Re-running the playbook rewrites the file.

**Ops**: Add an `ops:` list of Minecraft usernames to any server entry. The playbook looks up each UUID from the Mojang API (`api.mojang.com`) and writes `ops.json`. Players not found (404) are silently skipped. Ops are only written if the list is non-empty; servers without an `ops:` key get no ops.json.

**Java version** is auto-selected by `tasks/set_java_version.yml`: Java 25 / GraalVM CE 25 (MC 26.x+, year-based versioning), Java 21 / GraalVM CE 21 (MC 1.21+ or 1.20.5+), Java 17 / Temurin (1.18–1.20.4), Java 8 / OpenJDK (1.17 and below). MC version major > 1 always maps to Java 25.

**CurseForge provisioning** in the role delegates to `update-modpack.sh --no-wait` rather than reimplementing the API logic. The script and its config are deployed in step 5 (before the download steps) for this reason.

**Backup job**: At the end of Play 1, the playbook creates or updates a Proxmox cluster backup job (comment: `Minecraft Server Backups`, schedule: `0 * * * *`, storage: `mnemosyne`, mode: snapshot, compress: zstd). If the job already exists it merges the provisioned VMIDs into the existing VMID list. Identified by the comment string — don't rename it in the Proxmox UI. `proxmox_backup_storage` in `group_vars/all.yml` controls the target storage.

## Modpack update script (`update-modpack.sh`)

Deployed to each server LXC at `/usr/local/bin/update-modpack.sh`. Config at `/etc/minecraft/update.conf`.

Flow: Discord announce → 5-min countdown (skipped with `--no-wait`) → stop service → backup mods (keep 3) → wipe mods → download → extract → start service → Discord success.

`--no-wait` is used by the Ansible role for initial provisioning.

## Systemd on server LXCs

Uses a template unit `minecraft@.service` with `EnvironmentFile=/etc/minecraft/%i.env` for per-instance JVM heap. Start/stop a server: `systemctl start minecraft@<instance_name>`. Updates run nightly via `minecraft-update.timer` (4AM, `Persistent=true`).
