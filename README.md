# HomelabAnsible

Monorepo for all Ansible automation in the homelab: a 3-node Proxmox VE cluster
(`cluster-nash`: nyx, prometheus, atlas), a Proxmox Backup Server (mnemosyne),
and Minecraft server LXCs.

## Projects

| Directory | What it manages | Docs |
|---|---|---|
| [`proxmox/`](proxmox/) | Proxmox VE cluster: repos, cluster setup, PBS storage/backup jobs, ISO/template management, ~15 managed app LXCs, VM deploys, updates, restores, network tuning | [README](proxmox/README.md) |
| [`pbs/`](pbs/) | Proxmox Backup Server: install, NFS datastore, users, sync/pull jobs, Tailscale | [README](pbs/README.md) |
| [`minecraft/`](minecraft/) | Minecraft server LXC provisioning via the Proxmox API + nightly Modrinth/CurseForge modpack update script | [README](minecraft/README.md) |
| [`truenas/`](truenas/) | TrueNAS host `erebus`: full desired-state config (users, datasets, shares, services, apps) via middleware APIs, with read-only discovery and audit playbooks | [README](truenas/README.md) |

Each project is self-contained: it has its own `ansible.cfg`, inventory, and
vault, and is run from inside its own directory. There is no shared root
playbook — the projects target different machines with different credentials.

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
```

See each project's README for setup (copying `.example` files, vault
encryption, collections to install).

## Secrets policy

Real inventories, vaults, and credential files are **gitignored per project**
and only `.example` templates are tracked:

- `minecraft/ansible/vault.yml` — vault-encrypted, gitignored
- `proxmox/inventory.yml`, `proxmox/group_vars/proxmox_cluster.yml`,
  `proxmox/host_vars/*.yml` (except `example.yml`), `proxmox/files/gallery-dl-cookies.txt` — gitignored
- `pbs/inventory.yml`, `pbs/group_vars/pbs_servers.yml`, `.vault_pass` — gitignored
- `truenas/artifacts/*` (raw discovery output, config backups) and
  `truenas/inventory/host_vars/**/vault.yml` — gitignored; its tracked
  inventory/desired-state files are deliberately sanitized (no hashes/secrets)

Before committing, run `git status` and confirm none of the above appear.

## Network reference

| Resource | Address |
|---|---|
| Proxmox nodes | nyx 10.10.30.2 (cluster VIP), prometheus 10.10.30.3, atlas 10.10.30.9 |
| PBS (mnemosyne) | 10.10.20.2 |
| TrueNAS (erebus) | 10.10.10.7 (SSH port 2747) |
| apt-cacher-ng | 10.10.40.175:3142 (VLAN 40) |
| Guest network | 10.10.40.0/24 (VLAN 40, bridge `vmbr0`) |
| Corosync ring1 | 10.10.50.0/24 |
