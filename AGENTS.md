# AGENTS.md

Guidance for AI agents working in this monorepo. It merges several formerly
separate repos; each subdirectory is a self-contained Ansible project run from
inside its own directory.

## Layout

- `proxmox/` — Proxmox VE cluster automation. Deep agent docs: `proxmox/CLAUDE.md` / `proxmox/AGENTS.md`.
- `pbs/` — Proxmox Backup Server setup (`pbs/README.md`).
- `minecraft/` — Minecraft LXC provisioning + modpack update script. Agent docs:
  `minecraft/CLAUDE.md`. If a modpack misbehaves in a way that isn't an
  obvious single-mod config bug (e.g. a client crash tied to a corrupted
  network sync packet), prefer recreating the server from the modpack's
  official server pack (`pack_source: manual` in `servers.yml`, deployed via
  `minecraft/update-script/apply-manual-pack.sh` — supports both CurseForge
  server-pack zips and Modrinth `.mrpack` files) over continuing to debug the
  CurseForge/Modrinth auto-fetched mod set — see `minecraft/CLAUDE.md` for the
  procedure. External access is `<name>.mc.wbreiler.com` via a per-server DNS
  SRV record (Cloudflare, managed by hand, not part of this repo) plus a
  router port-forward — see `minecraft/CLAUDE.md` for the current port table.
- `truenas/` — Desired-state config for TrueNAS host `erebus`. **Read
  `truenas/AGENTS.md` before touching it** — it has strict safety rules
  (read-only discovery, explicit approval for anything destructive, never
  touch pools/network/SSH/the Ansible account).
- `arista/` — Core switch (192.168.1.222). It is the L3 gateway for every
  homelab VLAN: a bad change here takes down storage, IPMI, and the Proxmox
  cluster at once. Config changes require explicit user approval; management
  access is in-band (Vlan1 SVI), so never touch Vlan1, Et1 (uplink), or the
  admin account without a confirmed out-of-band path.
- `desktop/` — Windows 11 gaming PC (`gaming-pc`) over Windows OpenSSH
  (`desktop/README.md`).
- `mac/` — macOS fresh-install provisioning, runs on `localhost` only, no
  inventory (`mac/CLAUDE.md`).

Always `cd` into the project directory before running ansible — each has its
own `ansible.cfg` (inventory, SSH key, become settings) that only applies from
there.

## Subagents

Bounded subagent use is allowed for repo-wide reviews and implementation when
the work can be split into independent project or validation scopes. Give each
subagent an explicit file/directory boundary, preserve the safety rules in this
file and any deeper `AGENTS.md`, and have the coordinating agent review and
validate all combined changes. Subagents do not broaden authorization: they
must not run live infrastructure changes, destructive operations, network
installs, commits, or pushes unless the user has separately authorized that
exact action.

## Hard rules

1. **Never commit secrets or machine-specific configuration.** Real
   `inventory.yml`, local data-bearing `group_vars/*.yml`,
   `host_vars/*.yml`, `vault.yml`, repo-local `.vault_pass` files, and
   `proxmox/files/gallery-dl-cookies.txt` are gitignored. Their sanitized
   templates use the `*.yml.example` suffix and remain tracked. Reusable
   Ansible implementation files—playbooks, roles, tasks, handlers, defaults,
   and requirements—remain tracked as ordinary `.yml`. Check `git status`
   before every commit. `kuma/` stores its vault password outside the repository
   at `~/.config/ansible/vault-passwords/kuma`.
2. **Always commit completed changes, but never push.** Create a separate,
   scoped commit for each top-level project directory changed (`proxmox/`,
   `pbs/`, `minecraft/`, `truenas/`, `arista/`, `kuma/`, `desktop/`, or
   `mac/`). Keep root-level policy or documentation changes in their own
   commit. The user pushes.
3. **VMID 300 is reserved** (DiscoPanel on prometheus). Allocate new Minecraft
   servers the next unused sequential VMID in the 100 range after checking live
   cluster state; do not jump to 301+.
4. **LXCs are unprivileged** unless they NFS-mount. The `gallery_dl` LXC is privileged.
5. **Pinned versions**: third-party artifacts in `proxmox/` roles are
   version-pinned and checksum-verified. Bump version + checksum together.
6. **Secrets stay out of logs and argv**: use `no_log: true` and interactive
   prompts (`expect`) for passwords, as existing roles do.

## Validation

```bash
ansible-lint                                   # must pass in proxmox/ before claiming done
ansible-playbook -i inventory.yml site.yml --syntax-check
ansible-playbook ... --check --diff            # dry-run
```

Commit style: `role_name: brief description` (see `proxmox/CLAUDE.md`).

## Environment facts

- Cluster `cluster-nash`: nyx (10.10.30.2, VIP), prometheus (10.10.30.3),
  atlas (10.10.30.9) — PVE 9 / Debian trixie.
- PBS: mnemosyne (10.10.20.2), NFS-backed `MainStore` datastore.
- TrueNAS: erebus (10.10.10.7, SSH port 2747), key auth via 1Password agent.
- SSH keys: `~/.ssh/cluster-nash` (proxmox, via 1Password agent),
  `~/.ssh/lxc_nash` (minecraft LXCs).
- Host key checking uses `StrictHostKeyChecking=accept-new` (trust on first
  use). If a host is legitimately reinstalled, remove its old key with
  `ssh-keygen -R <host>` — do not weaken this back to `no`.
