# AGENTS.md

Guidance for the retired Uptime Kuma project. Follow the
[root guidance](../AGENTS.md) and [README](README.md). Run local checks from
`kuma/` so its configuration and relative paths apply.

## Retirement and ownership

The user confirmed retirement on 2026-10-02. Retained code and ignored
inventory do not establish live hosts or authorize deployment. Require a new
deployment request before activating services or restoring a site.

`site.yml` targets `kuma_hosts`. It configures OS updates, Tailscale, the
optional quorum relay, and Docker-based Uptime Kuma. It is not read-only.

`bootstrap-lxc.yml` targets `pve_hosts` and retains direct guest creation,
TUN passthrough, PBS connection, and backup-job writes for the former
standalone-site design. Never run it against Terraform-owned `cluster-nash`
or reconnect these legacy owners to active cluster playbooks.

## Code map and behavioral contracts

| Area | Contract |
| --- | --- |
| `roles/uptime_kuma` | Docker deployment plus optional API reconciliation in `files/configure.py` |
| `roles/quorum_relay` | Primary-based vote collection and Discord delivery in `files/quorum_relay.py` |
| `roles/apt_auto_update` | Host package maintenance through unattended upgrades |
| `roles/tailscale` | Connectivity and protected authentication |
| `roles/bootstrap_lxc`, `roles/pve_backup` | Retained standalone-site provisioning and backup code |

The default image is the rolling Kuma `2` tag. The API client path supports
Kuma 1.x and is disabled by default. Do not enable it against Kuma 2 or claim
that deploying the relay configures monitors in the UI. OS unattended upgrades
do not refresh the Docker image. The deployment role handles image pulls.

API reconciliation is additive. Preserve manually created monitors and groups
and the existing separation of shared, site-specific, and peer monitors.
Shared notifications use one designated primary. Site-specific and peer
notifications remain independent.

Quorum requires at least three sites and exactly one primary. There is no
primary election or failover. Preserve stale-vote handling and transition-only
notifications. The relay listens on all IPv4 interfaces. Container loopback
does not reach this host service, despite the current webhook template's
loopback URL. Review and test that path before any new deployment.

Setting the relay flag false stops and removes an existing relay unit.
It is not a read-only disable flag. Docker socket monitoring remains off by
default because even a read-only socket mount provides root-equivalent access.

## Local configuration and secrets

Real inventory, group variables, host variables, and `vault.yml` are ignored.
Use their sanitized examples. `ansible.cfg` reads the vault password from
`~/.config/ansible/vault-passwords/kuma`, outside the repository. Do not move
it beside the encrypted vault or print it during validation.

Preserve `no_log`, private generated configuration, and secret cleanup.
`pve_backup` supplies the PBS password through an `expect` prompt with echo
disabled. It installs `python3-pexpect` only for a missing storage target.
Do not revert to a password value in argv. Keep the existing SSH
`StrictHostKeyChecking=accept-new` policy and configured agent.

Do not delete retained application data, backups, or recovery material during
reference-code maintenance. The local `HANDOFF.md`, when present, is ignored
historical context and is not a tracked dependency.

## Validation

These checks do not activate the retired deployment:

```sh
ansible-lint
ansible-playbook site.yml --syntax-check
ansible-playbook bootstrap-lxc.yml --syntax-check
python3 roles/uptime_kuma/test_configure.py
python3 roles/quorum_relay/test_quorum_relay.py
python3 roles/pve_backup/test_secret_transport.py
git diff --check
```

Use Ansible's Python environment for fixtures that require PyYAML. Syntax
checks need the local Vault/inventory prerequisites. Do not weaken secret
handling to bypass a missing prerequisite. API tests stub the client, and
relay tests exercise local logic. Neither proves network delivery or Kuma 2
compatibility. Live checks require the separately authorized deployment scope.
