# Gaming PC Ansible setup

Configures the Windows 11 gaming PC `ORION` over WinRM.

For a new controller or Windows installation, start with the role's
[first setup guide](roles/gaming_pc/README.md). It separates the one-time
Windows bootstrap, local inventory and vault creation, read-only connection
test, check-mode preview, live application, and interactive-user follow-up.

## Responsibility boundary

The custom ORION ISO owns the complete non-secret baseline: applications, WSL,
Hyper-V and Virtual Machine Platform, user-profile applications, initial
drivers, and initial updates. It intentionally excludes 1Password after the
migration to Bitwarden.

This Ansible project owns protected and continuing live state:

- Versioned AMD chipset, Realtek audio/LAN, and detected Realtek or MediaTek
  Wi-Fi/Bluetooth driver validation and remediation for the Gigabyte X870
  EAGLE WIFI7
- Continuing Windows, Microsoft-product, and signed hardware-driver updates
- Persistent, all-user `Z:` mapping to `\\10.10.20.3\clips` as SMB user
  `wbreiler`
- The separately bootstrapped local `ansible` administrator and WinRM access

`gaming_pc_install_approved_applications` is disabled, and the WinGet,
interactive-user package, and optional-feature lists are empty. The role does
not duplicate the ISO-owned software baseline. Windows/driver updates,
motherboard-driver remediation, and the SMB mapping retain separate controls.

Motherboard drivers are pinned to checksum-verified packages from Gigabyte's
X870 EAGLE WIFI7 support page. Board revisions use either Realtek RTL8922AE or
MediaTek wireless modules, so the role detects the installed hardware and
refuses to guess when it cannot identify the module. The AMD chipset package
also supplies the applicable X3D components.

GPU drivers are maintained through the Windows Update driver catalog after the
ISO installs the initial RX 7900 XT driver. AMD Radeon Software, ASTRO Command
Center, ChatGPT, and iCloud are installed by the ISO in the normal desktop-user
context. They are not installed over WinRM, which would attach user-scoped
packages to the local `ansible` account.

This desired state is AMD-specific: the interactive application list no longer
includes Intel or NVIDIA GPU companion software. The full AMD companion
application is not treated as the driver source and is not silently installed.

## Managed hardware

The AMD gaming PC uses:

- AMD Ryzen 7 9800X3D
- Thermalright AXP90-X47 Full CPU cooler
- Gigabyte X870 EAGLE WIFI7 motherboard
- 48 GB (2 x 24 GB) Crucial Pro DDR5-6000 CL48 memory
- 1 TB Crucial P310 PCIe 4.0 NVMe SSD
- Sapphire Pulse Radeon RX 7900 XT 20 GB
- Fractal Design Terra Mini ITX case
- Asus ROG Loki 750 W 80+ Platinum SFX power supply

BIOS updates remain intentionally outside this role because an interrupted or
incorrect motherboard flash can make the PC unbootable. Confirm the board
revision and choose a stable BIOS through Gigabyte's support page separately.

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
