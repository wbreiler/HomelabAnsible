# Security Sweep TODO

Completed findings from the repo-wide security sweep performed on 2026-08-13.
Every recorded item below is fixed; this file remains as the audit record.

## Good news first

Secrets hygiene is solid: every vault/inventory/group_vars file with real
credentials is gitignored and untracked, `.example` files are clean, `no_log`
is used consistently on password/token tasks, TLS validation is on by
default everywhere except one local override (see High), no `curl | bash`,
and all pinned third-party downloads are checksum-verified.

## High

- [x] **Minecraft: secrets leak into `--diff` output.** The
  "Deploy /etc/minecraft/update.conf" task
  (`minecraft/ansible/roles/minecraft_server/tasks/main.yml:205-211`,
  template `templates/update.conf.j2:20-21`) has no `no_log`. The template
  renders `CURSEFORGE_API_KEY` and `DISCORD_WEBHOOK_URL` in plaintext, and
  the documented `--check --diff` workflow prints the full rendered file
  (both secrets) to stdout/logs.
- [x] **Minecraft: TLS verification disabled against Proxmox API.**
  `minecraft/ansible/group_vars/all.yml:20` (local, not committed) sets
  `proxmox_validate_certs: false`, so every Proxmox API call in
  `provision.yml`, `ha.yml`, and `tasks/manage_ha.yml` — which send
  `proxmox_api_password` and session cookies — skips certificate validation.
  The tracked `all.yml.example` correctly defaults this to `true`; the live
  config has drifted. Re-enable it, or add a real trusted cert.

## Medium

- [x] **PBS: password auth forced over SSH for every task.**
  `pbs/ansible.cfg:23` sets `PubkeyAuthentication=no`, so all `pbs`
  playbook runs use SSH password auth instead of keys. That password is
  also reused as the PBS namespace-creation secret
  (`pbs/roles/pbs/tasks/main.yml:136`), so one credential covers both SSH
  login and PBS admin. Switch to key auth for routine runs; reserve
  password auth for bootstrap only.
- [x] **Proxmox/diun: webhook config written without a file mode.**
  `proxmox/roles/diun/tasks/main.yml:204` writes `diun.yml` (contains
  `diun_discord_webhook_url`, see `templates/diun.yml.j2:12`) via shell
  redirection with no `umask`/mode, so it inherits the default (typically
  0644, world-readable) instead of the `0600` used by sibling roles
  (`update_reminder`, `healthcheck_reminder`).
- [x] **Proxmox: four systemd services run as root unnecessarily.**
  `roles/prowlarr/templates/prowlarr.service.j2`,
  `roles/seerr/templates/seerr.service.j2`, and
  `roles/gitea_mirror/templates/gitea-mirror.service.j2` lacked a
  `User=` directive. The retired Stash role was removed. Sibling roles
  already define a dedicated service user, so these roles now match them.
- [x] **Proxmox: Pocket ID and Spoolman explicitly run as root.**
  `roles/pocket_id/templates/pocketid.service.j2:6-7` and
  `roles/spoolman/templates/spoolman.service.j2:11` set
  `User=root`/`Group=root`. Pocket ID is an SSO/identity provider —
  running it as root is an unnecessary privilege-escalation vector if the
  app is ever compromised.

## Low

- [x] **Octopi: vault password lives next to the vault it decrypts.**
  `octopi/.vault_pass` and `octopi/vault.yml` sit in the same directory.
  Both are gitignored, but a filesystem backup/sync tool would scoop up
  the password and the encrypted payload together, defeating the
  separation vault-password files exist for. Move `.vault_pass` outside
  the repo tree.
- [x] **Proxmox/spoolman: `.env` copied without a mode.**
  `roles/spoolman/tasks/main.yml:171` does
  `cp .env.example .env` and inherits whatever mode ships in the
  upstream archive, unlike `gitea_mirror`/`pocket_id`/`bambuddy`, which
  explicitly harden their `.env` file modes.
- [x] **Proxmox: a few shell interpolations are unquoted.**
  `tasks/create_lxc.yml:15` (awk match on `{{ lxc_hostname }}`),
  `roles/manage_isos/tasks/main.yml:26-33` (`wget` URL/filename), and
  `roles/vm_deploy/tasks/create_vm.yml` (several `{{ item.* }}` fields in
  a shell `ARGS` block) interpolate operator-controlled variables into
  shell strings without quoting. Values come only from your own
  inventory/group_vars, so exploitability is minimal, but a stray shell
  metacharacter in a hostname would break the command. Quote for
  robustness.
- [x] **`proxmox/tests/ansible.cfg` disables host key checking.** Fine for
  a `localhost`-only test fixture (confirmed — see
  `proxmox/tests/test-inventory.yml`), but worth a one-line comment
  noting why, so it doesn't get copied into a real config later.
