# ORION ISO gap report

This document defines the responsibility boundary between the custom Windows 11
Pro ISO and the post-install Ansible workflow. The ISO owns the complete
non-secret baseline. Ansible owns credentials, remote-management bootstrap, the
protected SMB mapping, and later validation or remediation.

## ISO responsibility: non-secret baseline

The completed ISO must:

- Install Windows 11 Pro on the operator-selected disk. Disk selection remains
  manual; the ISO must never erase the automatically detected “smallest” disk.
- Set hostname `ORION`, enable dark mode, remove OneDrive without deleting user
  data, and enable both Hyper-V and `VirtualMachinePlatform`.
- Install WSL and every approved application from the September 4 report plus
  7-Zip, Audacity, Bambu Studio, Battle.net, CrystalDiskInfo, HandBrake,
  Node.js LTS, OBS Studio, Parsec, Plex, TightVNC, and VLC.
- Install ASTRO Command Center, ChatGPT, and iCloud in the normal desktop-user
  context rather than the automation account.
- Install Bitwarden. Do not install 1Password; the user migrated to Bitwarden.
- Bundle and install the exact AMD X870 chipset, Ethernet, Wi-Fi, Bluetooth,
  audio, and RX 7900 XT drivers. Confirm the X870 EAGLE WIFI7 board revision and
  detect Realtek versus MediaTek wireless hardware instead of guessing.
- Make the matching network drivers available offline. ORION is configured for
  AHCI/NVMe with RAID disabled, so do not add AMD RAID preinstallation drivers
  or RAIDXpert2 to the image.
- Install GIGABYTE Control Center and the RGB Fusion/ARGB component.
- Run Windows, Microsoft-product, and signed hardware-driver updates, handling
  and logging required reboots.
- Record package sources, versions, SHA-256 checksums, signatures, hardware
  applicability, install results, and reboot state.

The ISO must contain no reusable passwords, vault data, SMB credentials, or
management-account secrets.

## Ansible responsibility: protected and live state

After the normal desktop user can sign in, Ansible remains responsible for:

- Creating or repairing the dedicated local `ansible` administrator and
  enabling WinRM through the interactive `bootstrap-winrm.ps1` flow. The
  password is prompted for locally and then stored only in Ansible Vault.
- Creating the persistent all-user `Z:` mapping to `\\10.10.20.3\clips` with
  the SMB credential stored only in Ansible Vault.
- Revalidating the exact motherboard and wireless hardware before applying the
  checksum-pinned chipset, audio, LAN, Wi-Fi, or Bluetooth driver packages as
  remediation. Unknown hardware must stop safely rather than receive a guess.
- Re-running Windows, Microsoft-product, and signed hardware-driver updates as
  continuing desired-state maintenance.
- Reporting drift and repairing missing protected/live configuration without
  duplicating ISO-owned application or optional-feature installation.

Accordingly, `gaming_pc_install_approved_applications` is disabled and the
role's WinGet, interactive-user package, and optional-feature lists are empty.
Driver/update controls remain enabled as post-install validation and recovery.

## Remaining validation before use

- Confirm the exact motherboard revision and installed wireless PNP hardware.
- Verify every WinGet ID, source URL, checksum, signature, and silent argument.
- Validate the answer file and injected `boot.wim`/Windows 11 Pro indexes.
- Test Setup and reboot behavior in a VM, then on isolated ORION hardware.
- Inspect Device Manager and test Ethernet, Wi-Fi, Bluetooth, audio, GPU,
  Stream Deck, Meta Quest Link, WSL, Hyper-V, and ARGB control.
- Review installation logs and verify the complete state again after reboot.
- Only after the ISO passes those checks, bootstrap Ansible, preview with
  `--check --diff`, and apply the credentialed/live configuration.
