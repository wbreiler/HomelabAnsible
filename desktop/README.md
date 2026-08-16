# Gaming PC Ansible setup

Configures a Windows 11 gaming PC named `gaming-pc` over WinRM.

## Managed state

- Steam, Discord, Chrome, OBS Studio, Epic Games Launcher, Apple Music,
  iCloud for Windows, and Elgato Stream Deck
- Windows, Microsoft product, and signed hardware-driver updates
- Persistent `Z:` mapping to `\\10.10.20.3\clips` as SMB user `wbreiler`

The Radeon driver is installed from the Windows Update driver catalog. This is
the hardware-matched, signed route; the role intentionally does not download a
version-specific AMD web installer that will become stale.

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

WinGet's Microsoft Store packages can require Store availability and may need a
first interactive launch to complete account sign-in. The SMB mapping belongs
to `Techn`; sign out and back in if Explorer does not show it immediately after
the first run.
