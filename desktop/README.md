# Gaming PC Ansible setup

Configures a Windows 11 gaming PC named `gaming-pc` over Windows OpenSSH.

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
`bootstrap-openssh.ps1` to it, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\bootstrap-openssh.ps1
```

The bootstrap installs Microsoft's Windows OpenSSH Server, starts it, opens TCP
22 in Windows Firewall, and makes Windows PowerShell the default SSH shell.

## 2. Configure this project

On the Ansible controller:

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.yml.example inventory/hosts.yml
cp group_vars/gaming_pc/vault.yml.example group_vars/gaming_pc/vault.yml
```

Replace `192.0.2.10` in `inventory/hosts.yml` with the PC's IP. Put the SMB
password in `vault.yml`, then encrypt it immediately:

```bash
ansible-vault encrypt group_vars/gaming_pc/vault.yml
```

The real inventory and vault are ignored by Git.

## 3. Connect and apply

The first SSH connection records the PC host key. Test access and the playbook:

```bash
ssh Techn@<gaming-pc-ip>
ansible gaming_pc -m ansible.windows.win_ping --ask-pass
ansible-playbook site.yml --ask-pass --ask-vault-pass --check
ansible-playbook site.yml --ask-pass --ask-vault-pass
```

WinGet's Microsoft Store packages can require Store availability and may need a
first interactive launch to complete account sign-in. The SMB mapping belongs
to `Techn`; sign out and back in if Explorer does not show it immediately after
the first run.
