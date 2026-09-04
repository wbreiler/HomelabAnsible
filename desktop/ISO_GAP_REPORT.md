# ORION ISO gap report

The Ansible role now assumes the custom ISO installs the applications named in
the September 4 deployment report and enables Hyper-V. Those confirmed overlaps
were removed from the role.

## The ISO still needs to do

- Bundle and install the correct AMD X870 chipset, Ethernet, Wi-Fi, Bluetooth,
  audio, and RX 7900 XT drivers. Detect the board revision and wireless hardware
  instead of guessing; include offline network drivers and add a storage driver
  only if RAID is actually enabled.
- Install the playbook-only machine applications if the goal is for a fresh ISO
  installation to reach the same state without Ansible: 7-Zip, 1Password,
  Audacity, Bambu Studio, Battle.net, CrystalDiskInfo, HandBrake, Node.js LTS,
  OBS Studio, Parsec, Plex, TightVNC, VLC, and WSL.
- Enable the separate `VirtualMachinePlatform` Windows feature required by WSL.
  Enabling Hyper-V does not make that explicit playbook step redundant.
- Install ASTRO Command Center, ChatGPT, and iCloud in the normal desktop user
  profile if those applications should be present immediately.
- Run Windows, Microsoft product, and signed hardware-driver updates, including
  any required reboots.
- Create the persistent all-user `Z:` mapping to `\\10.10.20.3\clips`. This
  requires the SMB credential, so it may be safer to leave it in the encrypted
  Ansible workflow.
- Create or repair the dedicated local `ansible` administrator and enable WinRM
  if the PC will continue to be managed by this playbook. Do not bake its
  password into the ISO.

The ISO report already lists the right remaining validation work: verify WinGet
IDs, checksums and signatures; validate injected WIM indexes; test in a VM and
on isolated ORION hardware; inspect Device Manager; review logs; and verify the
state again after reboot.
