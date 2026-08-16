# Gaming PC Ansible setup

Configures a Windows 11 gaming PC named `gaming-pc` over WinRM.

## Managed state

- Machine-wide gaming, media, browser, streaming, remote-access, 3D-printing,
  hardware-monitoring, and development applications discovered on `KRATOS`
- Windows Subsystem for Linux and its Virtual Machine Platform dependency
- Windows, Microsoft product, and signed hardware-driver updates
- Persistent, all-user `Z:` mapping to `\\10.10.20.3\clips` as SMB user
  `wbreiler`

The NVIDIA driver is installed from the Windows Update driver catalog. This is
the hardware-matched, signed route; the role intentionally does not download a
version-specific NVIDIA web installer that will become stale.

Apple Music, Discord, iCloud for Windows, and NVIDIA App remain interactive
`Techn`-profile installs. Installing them through WinRM would attach them to the
local `ansible` account instead of the desktop user.

## 1. Bootstrap the PC once

Open PowerShell **as Administrator** on the gaming PC, copy
`bootstrap-winrm.ps1` to it, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\bootstrap-winrm.ps1
```

Enter a strong password when prompted. The bootstrap creates a dedicated local
administrator account named `ansible`, enables WinRM, and permits that local
administrator to receive an elevated remote token. The password is read as a
secure string and is not written to disk.

The script is idempotent. On later runs it preserves the existing account and
password while repairing its enabled, administrator, and WinRM state.

## 2. Configure this project

On the Ansible controller:

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.yml.example inventory/hosts.yml
cp group_vars/gaming_pc/vault.yml.example group_vars/gaming_pc/vault.yml
```

Update the IP and computer-qualified username in `inventory/hosts.yml` if they
change. Put both the local `ansible` account password and SMB password in
`vault.yml`, then encrypt it immediately:

```bash
ansible-vault encrypt group_vars/gaming_pc/vault.yml
```

The real inventory and vault are ignored by Git.

## 3. Connect and apply

Test WinRM access and the playbook:

```bash
ansible gaming_pc -m ansible.windows.win_ping --ask-vault-pass
ansible-playbook site.yml --ask-vault-pass --check --diff
ansible-playbook site.yml --ask-vault-pass
```

The role registers the PC's existing Microsoft App Installer package for the
automation account before invoking WinGet. It uses a global SMB mapping so
`Z:` is also visible in the interactive `Techn` session.
