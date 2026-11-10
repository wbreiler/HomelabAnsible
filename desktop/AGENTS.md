# AGENTS.md

Guidance for the Windows gaming PC project. Follow the
[root guidance](../AGENTS.md), [README](README.md), and
[first setup guide](roles/gaming_pc/README.md). Run Ansible from `desktop/`.

## Scope and ownership

`site.yml` targets `gaming_pc` and imports `gaming_pc`. It configures an
existing Windows installation through WinRM. The custom ORION ISO owns the
non-secret baseline: applications, WSL, optional features, initial drivers,
and initial updates. Preserve the ISO/Ansible split established in Git history.

Ansible owns continuing Windows/driver updates, motherboard-driver remediation,
and the persistent global SMB mapping. The optional `clips_route` tag manages
only the SMB server's IPv4 host route. Configure its on-link gateway in the
private inventory. The role does not install Windows, partition
disks, create the interactive user, configure dual boot, or update BIOS firmware.

## Code and configuration

| Path | Responsibility |
| --- | --- |
| `bootstrap-winrm.ps1` | One-time administrator bootstrap for the local automation account and WinRM |
| `copy-clips.ps1` | Per-user Explorer Send To shortcut. Preserve single-threaded batches and delete only a verified local original after the published SMB file passes flush and hash checks. Run `-Install` as the desktop user. |
| `group_vars/gaming_pc/main.yml` | Tracked non-secret desired state, update controls, driver pins, and SMB settings |
| `roles/gaming_pc/tasks/main.yml` | Application gate, updates, optional features, and SMB mapping |
| `roles/gaming_pc/tasks/motherboard_drivers.yml` | Hardware detection, verified downloads, installer markers, and reboot handling |
| `inventory/hosts.yml`, `group_vars/gaming_pc/vault.yml` | Ignored inventory and encrypted credentials, created from examples |

`gaming_pc_install_approved_applications` is false and the package/feature
lists are empty. Do not restore ISO-owned installs during maintenance.
User-scoped apps installed through WinRM would belong to the automation
account. Keep interactive-user installation in the documented desktop workflow.

Windows updates, driver updates, motherboard drivers, and reboots have
separate controls. A normal live run can reboot Windows. Review those flags
and the user's active session before applying changes.

## Hardware and credential safeguards

- Preserve the exact motherboard assertion and wireless-vendor detection.
  The recorded board is a Gigabyte X870 EAGLE WIFI7. Do not guess between
  Realtek and MediaTek packages when the detected hardware is unknown.
- Bump each driver version, source URL, and SHA-256 together. Preserve the
  one-installer assertion, accepted exit codes, temporary cleanup, and
  reboot-required propagation. The marker records installation, not the loaded
  driver version. Verify Device Manager after an authorized update.
- The bootstrap prompts for a new account password and preserves an existing
  account's password. It enables WinRM and elevated remote tokens for local
  administrators. Do not use it as a routine credential-rotation mechanism.
- Keep WinRM and SMB passwords in Vault. The SMB task uses a `SecureString`
  sensitive parameter and `no_log`. Preserve both. A mapping at the same
  path skips reconciliation, so it does not prove changed credentials were applied.
- The inventory example uses NTLM over HTTP port 5985 on the trusted LAN.
  `host_key_checking` is not proof of WinRM TLS. Do not expose WinRM publicly
  or weaken authentication to work around a failed connection.

The SMB task replaces a different mapping at the selected drive letter.
Review that target before a change and verify access as the interactive user.
The recorded `Z:` destination and October 2 connection failures are historical
context. They do not establish current availability or user access.

## Validation

Run static checks before connecting to Windows:

```sh
ansible-lint
ansible-playbook site.yml --syntax-check --ask-vault-pass
git diff --check
```

Use the configured Vault mechanism. Static syntax can use a sanitized example
inventory when no real target is configured. Never use it to claim live health.

For authorized Windows work, first require a successful
`ansible gaming_pc -m ansible.windows.win_ping --ask-vault-pass`, then review
`ansible-playbook site.yml --check --diff --ask-vault-pass`.
The setup guide documents macOS controller temporary paths and the WinRM
fork-safety environment setting. Install `pywinrm` in Ansible's own environment
when needed. A Windows Hello PIN does not authenticate this automation account.

Check mode cannot fully validate installers, loaded drivers, reboots, or
interactive-user applications. After a live change, check Windows Update,
Device Manager, pending reboot state, and the SMB drive in the user's session.
