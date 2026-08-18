# HomelabAnsible

Monorepo for all Ansible automation in the homelab: a 3-node Proxmox VE cluster
(`cluster-nash`: nyx, prometheus, atlas), a Proxmox Backup Server (mnemosyne),
and Minecraft server LXCs.

## Projects

| Directory | What it manages | Docs |
|---|---|---|
| [`proxmox/`](proxmox/) | Proxmox VE cluster: repos, cluster setup, PBS storage/backup jobs, ISO/template management, ~15 managed app LXCs, VM deploys, updates, restores, network tuning | [README](proxmox/README.md) |
| [`pbs/`](pbs/) | Proxmox Backup Server: install, local ZFS datastore, users, sync/pull jobs, Tailscale | [README](pbs/README.md) |
| [`minecraft/`](minecraft/) | Minecraft server LXC provisioning via the Proxmox API + nightly Modrinth/CurseForge modpack update script | [README](minecraft/README.md) |
| [`truenas/`](truenas/) | TrueNAS host `erebus`: full desired-state config (users, datasets, shares, services, apps) via middleware APIs, with read-only discovery and audit playbooks | [README](truenas/README.md) |
| [`arista/`](arista/) | Core switch (Arista DCS-7050SX-64): incremental, explicitly scoped desired-state management | [README](arista/README.md) |
| [`kuma/`](kuma/) | Uptime Kuma on one or more Mini PCs (multi-site, cross-monitored over Tailscale): Docker deploy, monitors/groups/notifications, quorum relay, apt auto-update | [README](kuma/README.md) |
| [`desktop/`](desktop/) | Windows 11 gaming PC (`gaming-pc`) over WinRM: apps, updates, SMB mapping | [README](desktop/README.md) |
| [`mac/`](mac/) | macOS fresh-install provisioning: Homebrew, Mac App Store apps, dotfiles, system defaults | [README](mac/README.md) |

Each project is self-contained and is run from inside its own directory so its
local configuration is used. Inventories and vaults exist where the target
requires them; `mac/` runs only on localhost. There is no shared root playbook
because the projects target different machines with different credentials.

## Quick start

```bash
# Proxmox cluster
cd proxmox && ansible-playbook -i inventory.yml site.yml --ask-vault-pass

# PBS server
cd pbs && ansible-playbook site.yml

# Minecraft servers
cd minecraft/ansible && \
  ssh-agent bash -c 'ssh-add ~/.ssh/lxc_nash && ansible-playbook provision.yml --ask-vault-pass'

# TrueNAS (audit first; convergence is site.yml)
cd truenas && ansible-playbook playbooks/audit.yml

# Uptime Kuma Mini PC(s)
cd kuma && ansible-playbook site.yml

# Gaming PC
cd desktop && ansible-playbook site.yml --ask-vault-pass

# Mac
cd mac && make run
```

See each project's README for setup (copying `*.yml.example` files, vault
encryption, collections to install).

## Secrets policy

Real inventories, vaults, and machine-specific configuration files are
**gitignored per project**. Sanitized configuration templates use the
`*.yml.example` suffix. Reusable playbooks, roles, tasks, and handlers remain
tracked as ordinary `.yml` because they are implementation code:

- `minecraft/ansible/vault.yml` — vault-encrypted, gitignored
- `proxmox/inventory.yml`, `proxmox/group_vars/proxmox_cluster.yml`,
  `proxmox/host_vars/*.yml`, `proxmox/files/gallery-dl-cookies.txt` —
  gitignored
- `pbs/inventory.yml`, `pbs/group_vars/pbs_servers.yml`, `.vault_pass` — gitignored
- `minecraft/ansible/servers.yml`, `group_vars/all.yml`, and `vault.yml` —
  gitignored; copy their tracked examples first
- `truenas/inventory/hosts.yml`, `group_vars/truenas.yml`, and host-specific
  desired-state/Vault files — gitignored; copy their tracked examples first
- `truenas/artifacts/*` (raw discovery output, config backups) and
  `truenas/inventory/host_vars/**/vault.yml` — gitignored; its tracked
  inventory/desired-state files are deliberately sanitized (no hashes/secrets)
- `arista/inventory.yml`, `arista/group_vars/arista.yml`, `.vault_pass`, and
  discovery artifacts — gitignored; copy the tracked examples before use
- `kuma/inventory.yml`, `kuma/group_vars/kuma_hosts.yml`, `kuma/vault.yml`,
  and each `kuma/host_vars/<hostname>/{vars,vault}.yml` — gitignored; the
  vault password lives outside the repository at
  `~/.config/ansible/vault-passwords/kuma`
- `desktop/inventory/hosts.yml` and `desktop/group_vars/gaming_pc/vault.yml` —
  gitignored; copy their tracked `*.yml.example` files first, then
  `ansible-vault encrypt` the vault file
- `mac/` has no vault: it manages only a local macOS user account, and
  `mac/.claude/` (local Claude Code settings) is gitignored

Before committing, run `git status` and confirm none of the above appear.

## Network reference

| Resource | Address |
|---|---|
| Proxmox nodes | nyx 10.10.30.2 (cluster VIP), prometheus 10.10.30.3, atlas 10.10.30.9 |
| PBS (mnemosyne) | 10.10.20.2 |
| TrueNAS (erebus) | 10.10.10.7 (SSH port 2747) |
| Core switch (Arista) | 192.168.1.222 — SVI gateways 10.10.10.2 (VLAN 10 ipmi), 10.10.20.1 (VLAN 20 storage), 10.10.30.1 (VLAN 30 proxmox-hosts), 10.10.40.1 (VLAN 40 proxmox-guests) |
| apt-cacher-ng | 10.10.40.175:3142 (VLAN 40) |
| Guest network | 10.10.40.0/24 (VLAN 40, bridge `vmbr0`) |
| Corosync ring1 | 10.10.50.0/24 |
