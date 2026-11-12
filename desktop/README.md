# Gaming PC Ansible setup

[Agent guidance](AGENTS.md) covers ISO ownership, driver safeguards, and validation.

Configures the Windows 11 gaming PC `ORION` over WinRM.

The configuration below describes intended behavior and recorded hardware.
The 2026-10-02 documentation review checked it against the role implementation.
The fresh WinRM probe timed out at `192.168.1.221:5985`, so installed software,
hardware details, updates, and the SMB mapping remain unverified. An earlier
probe in the same review reached WinRM but failed authentication.

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
  Wi-Fi/Bluetooth driver installation for the Gigabyte X870
  EAGLE WIFI7
- Continuing Windows, Microsoft-product, and signed hardware-driver updates
- Persistent, all-user `Z:` mapping to `\\10.10.20.3\clips` as SMB user
  `wbreiler`
- The separately bootstrapped local `ansible` administrator and WinRM access

Set `gaming_pc_clips_gateway` on the PC in the private inventory to route the
Clips server through an on-link IPv4 gateway. The role uses the IPv4 address
from `gaming_pc_smb_path` and adds a persistent `/32` route. To apply only this
route, run `ansible-playbook site.yml --tags clips_route --ask-vault-pass`.

### Move local clips from File Explorer

Run `.\copy-clips.ps1 -Install` from this directory in Windows PowerShell as the
desktop user. Select one or more finished files, then choose **Show more options
→ Send to → Clips**. The shortcut uses the user's SMB connection to
`\\10.10.20.3\clips`. It runs one single-threaded Robocopy command (`/J /MT:1`)
per source folder, using only the selected filenames. It skips names already
on the share. When selected files share a name, the first one wins.
After publishing a file under its final name, the script flushes it to the
share and compares its SHA-256 hash with the local original. A match allows
the script to permanently delete the original, bypassing the Recycle Bin.
Skipped files and network originals stay in place. A failed verification
leaves the original available for inspection, including files with additional
NTFS data streams. Verification reads the uploaded file back over SMB.
You can also run `.\copy-clips.ps1 "C:\Videos\My clip.mp4"` directly.

### Isolated Clips regression tests

Use a disposable Windows environment with Windows PowerShell 5.1, Robocopy,
and a local NTFS `%TEMP%`. The harness needs no Pester installation or admin
rights. From `desktop/`, run:

```powershell
powershell.exe -NoProfile -File .\tests\copy-clips.Tests.ps1
```

The harness creates synthetic recordings and destinations under a unique
temporary directory. It permanently deletes only these fixtures and removes
the directory afterward. Every transfer supplies the named `-Destination`
override. The production default remains `\\10.10.20.3\clips`, and the Send To
shortcut remains unchanged. Do not use real recordings as test fixtures.

The 26 cases cover parameter binding, real Robocopy uploads and SHA-256 checks,
existing destinations, duplicate names, batching, interrupted transfers,
missing or short copies, hash mismatches, concurrent publication, source
replacement, NTFS streams, open handles, relative paths, junctions, and cleanup.
Duplicate selections keep the existing first-wins behavior: the first file
can be deleted after verification. A second file with the same name stays.
Selecting the same path twice does not protect that file from verified deletion.

Fault cases replace only the Robocopy command expression in an in-memory copy
of the parsed script. They inject deterministic failures without changing the
verification or deletion functions. Real-copy cases execute the original script.
The harness checks errors, retained contents, published contents, and staging
cleanup. It prints PASS, FAIL, and SKIP results and exits nonzero on failure.

Two network-source cases skip unless you supply an **existing scratch share
on the disposable Windows machine**, for example:

```powershell
powershell.exe -NoProfile -File .\tests\copy-clips.Tests.ps1 -NetworkRoot '\\localhost\clips-test'
```

The harness accepts only localhost or loopback UNC paths. It creates a unique
fixture directory inside that share. The mapped-drive case temporarily maps
an unused drive letter without persistence, then removes that mapping.
Windows needs an enabled guest adapter for these SMB cases. An offline VM can
connect it only to an internal virtual hub, with no host or external network.
The harness does not create shares, change credentials, install the shortcut,
or change OBS, Ansible, routing, or the production share.

The [2026-11-11 isolated validation](tests/validation-2026-11-11.md) recorded
26 passed, 0 failed, and 0 skipped after correcting three harness issues.
It used Windows Server 2022 and localhost SMB, not the live gaming PC.

These tests do not prove SMB server durability, behavior during a process kill
or power loss, Explorer UI behavior, or the live gaming PC setup. Injected
transfer failures exercise normal exception cleanup, not recovery after a
terminated process. Run the Windows suite before relying on its regression
coverage. A static check on macOS cannot validate Windows file-handle semantics.

`gaming_pc_install_approved_applications` is disabled, and the WinGet,
interactive-user package, and optional-feature lists are empty. The role does
not duplicate the ISO-owned software baseline. Windows/driver updates,
motherboard-driver remediation, and the SMB mapping retain separate controls.

Motherboard drivers are pinned to checksum-verified packages from Gigabyte's
X870 EAGLE WIFI7 support page. Board revisions use either Realtek RTL8922AE or
MediaTek wireless modules, so the role detects the installed hardware and
refuses to guess when it cannot identify the module. The AMD chipset package
also supplies the applicable X3D components.

Driver tasks verify the board and wireless vendor before installation. A
package/version marker prevents repeat installation. They do not compare the
loaded driver version against that marker or verify installer signatures
separately from the configured SHA-256 checksum.

GPU drivers are maintained through the Windows Update driver catalog after the
ISO installs the initial RX 7900 XT driver. AMD Radeon Software, ASTRO Command
Center, ChatGPT, and iCloud are installed by the ISO in the normal desktop-user
context. They are not installed over WinRM, which would attach user-scoped
packages to the local `ansible` account.

This desired state is AMD-specific: the interactive application list no longer
includes Intel or NVIDIA GPU companion software. The full AMD companion
application is not treated as the driver source and is not silently installed.

## Managed hardware

The recorded hardware specification is below; this review did not verify it
on the PC:

- AMD Ryzen 7 9800X3D
- Thermalright AXP90-X47 Full CPU cooler
- Gigabyte X870 EAGLE WIFI7 motherboard
- Motherboard PCB revision 1.1 with Realtek RTL8922AE Wi-Fi 7/Bluetooth
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

If application installation is explicitly enabled, the role registers the
existing Microsoft App Installer package for the automation account before
invoking WinGet. That path is disabled by the current configuration. The role
uses a global SMB mapping intended to expose `Z:` to interactive users too.
