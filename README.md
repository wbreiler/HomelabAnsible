# HomelabAnsible

Monorepo for independently operated Ansible projects covering the Proxmox/PBS
core, Minecraft and application LXCs, TrueNAS, the core switch, multi-site
monitoring, and workstation provisioning.

## Documentation verification

The 2026-11-02 documentation review uses Git history through `1baea75` and
the tracked implementation. It does not recheck live hosts. See
[LIVE_AUDIT.md](LIVE_AUDIT.md) for the separate 2026-10-02 live check.
Historical audits, handoffs, and deployment counts remain dated records.
Role defaults and examples are not live inventory.

## Projects

| Directory | What it manages | Docs |
|---|---|---|
| [`terraform/`](terraform/) | Proxmox guests, backup jobs, HA policy, PBS storage connection, and media/templates with HCP state | [README](terraform/README.md) |
| [`proxmox/`](proxmox/) | Proxmox host repositories, cluster bootstrap, guest software, updates, restores, monitoring, and network tuning | [README](proxmox/README.md) |
| [`pbs/`](pbs/) | Existing Proxmox Backup Server: repository cleanup, local ZFS datastore, users, pull-style sync jobs, and Tailscale | [README](pbs/README.md) |
| [`minecraft/`](minecraft/) | Existing Minecraft guest configuration and modpack updates. Terraform owns the LXCs and HA policy | [README](minecraft/README.md) |
| [`truenas/`](truenas/) | TrueNAS host `erebus`: full desired-state config (users, datasets, shares, services, apps) via middleware APIs, with read-only discovery and audit playbooks | [README](truenas/README.md) |
| [`arista/`](arista/) | Core switch (Arista DCS-7050SX-64): incremental, explicitly scoped desired-state management | [README](arista/README.md) |
| [`kuma/`](kuma/) | Retired deployment; retained reference automation for Uptime Kuma: Docker deployment, Tailscale, optional API reconciliation/quorum relay, and apt auto-update | [README](kuma/README.md) |
| [`desktop/`](desktop/) | Windows 11 gaming PC (`gaming-pc`) over WinRM: apps, updates, SMB mapping | [README](desktop/README.md) |
| [`mac/`](mac/) | Local main/dev profiles and separate remote Intel bootstrap/full-dev playbooks | [README](mac/README.md) |

Run Terraform from `terraform/proxmox/` and Ansible from each project's
documented directory. Minecraft uses `minecraft/ansible/`. Mac `main.yml`
targets localhost, while `dev-host.yml` and `dev-vm.yml` require an explicit
remote inventory. There is no shared root playbook
because the projects target different machines with different credentials.

## Current workflow guides

- [Guest deployment](terraform/README.md#create-a-guest-and-install-its-application): Terraform provisioning followed by Gatus, Apt-Cacher NG, or LibreSpeed configuration.
- [LXC maintenance](proxmox/README.md#system-updates): guarded OS/application updates, backups, and Discord results.
- [Private HTTPS and DNS](proxmox/docs/local-services.md), [Homebridge discovery](proxmox/README.md#homebridge-discovery), and [NexDeck](proxmox/files/nexdeck/README.md).
- [TrueNAS cloud backups](truenas/files/cloud-backup/SETUP.md): encrypted data, consistent SQLite copies, and a media catalog. Media contents remain excluded.
- [Mac provisioning](mac/README.md): 1Password SSH, separate profiles, and reusable Intel support. [VM 108 is retired](proxmox/docs/macos-follow-up.md).

## Quick start

```bash
# Proxmox cluster
cd proxmox && ansible-playbook -i inventory.yml site.yml --ask-vault-pass

# PBS server
cd pbs && ansible-playbook site.yml --vault-password-file .vault_pass

# Minecraft servers
cd minecraft/ansible && \
  ansible-playbook provision.yml --private-key ~/.ssh/lxc.pub --ask-vault-pass

# TrueNAS (audit first; convergence is site.yml)
cd truenas && ansible-playbook playbooks/audit.yml

# Gaming PC
cd desktop && ansible-playbook site.yml --ask-vault-pass

# Mac
cd mac && make run
```

See each project's README for setup (copying `*.yml.example` files, vault
encryption, collections to install).
Run each example from the repository root. Review the project's safety rules
and check-mode output before a live application. Kuma remains retired.

## Secrets policy

Real inventories, vaults, and machine-specific configuration files are
**gitignored per project**. Sanitized configuration templates use the
`*.yml.example` suffix. Reusable playbooks, roles, tasks, and handlers remain
tracked as ordinary `.yml` because they are implementation code:

- `minecraft/ansible/vault.yml` — vault-encrypted, gitignored
- `terraform/proxmox/*.local.tf`, `.env`, private profiles, state, plans, and
  `artifacts/` — ignored deployment files, never documentation sources for secrets
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
- `mac/` has no vault: local and remote playbooks use the selected user's account, and
  `mac/.claude/` (local Claude Code settings) is gitignored

Before committing, run `git status` and confirm none of the above appear.

## Network reference

| Resource | Address |
|---|---|
| Proxmox nodes | prometheus 10.10.30.3, atlas 10.10.30.9 |
| PBS (mnemosyne) | 10.10.20.2 |
| TrueNAS (erebus) | 10.10.10.7 (SSH port 2747) |
| Core switch (Arista) | 192.168.1.222 — SVI gateways 10.10.10.2 (VLAN 10 ipmi), 10.10.20.1 (VLAN 20 storage), 10.10.30.1 (VLAN 30 proxmox-hosts), 10.10.40.1 (VLAN 40 proxmox-guests) |
| apt-cacher-ng | 10.10.40.175:3142 (VLAN 40) |
| Guest network | 10.10.40.0/24 (VLAN 40, bridge `vmbr0`) |
| Corosync ring1 | 10.10.50.0/24 |
