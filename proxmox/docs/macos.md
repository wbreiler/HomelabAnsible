# macOS Tahoe on Atlas

`macos.yml` creates VM 108 (`macos-tahoe`) on Atlas with 4 cores, 8 GiB RAM,
a 128 GiB Helios disk, and the existing VLAN 40 network. Check cluster allocation
before changing the ID. The playbook refuses an ID or name collision. It leaves
an existing VM untouched and does not start it automatically.

The VM MAC is pinned to `BC:24:11:20:25:AA`. The approved Arista DHCP
reservation assigns `10.10.40.9`. Switch configuration is managed separately
and is not changed by this playbook.

From `proxmox/`, use the existing inventory and normal Vault access, or an
isolated inventory that avoids unrelated cluster variables:

```bash
ansible-playbook -i 'atlas,' macos.yml --check --diff \
  -u root --private-key ~/.ssh/cluster.pub -e ansible_host=10.10.30.9
ansible-playbook -i 'atlas,' macos.yml \
  -u root --private-key ~/.ssh/cluster.pub -e ansible_host=10.10.30.9
```

The OpenCore ISO and recovery downloader come from
[OSX-PROXMOX](https://github.com/luchina-gabriel/OSX-PROXMOX) at revision
`576ea00a631b416232f5e04cdf6274e227ad82d7`. Both have SHA-256 checksums in the
playbook. Apple supplies the recovery image. The downloader verifies its image
chunks and Apple's chunklist signature before the playbook creates a FAT image.
The checksum-pinned OpenCore source is separate from the writable boot image.
The playbook seeds that boot image only when absent, preserving guest writes.
The first run requests Apple's latest recovery for the Tahoe board ID. A repeat
run preserves the existing image. Check mode skips media and VM creation.

The CPU arguments match upstream's Intel path for Atlas's Xeon Gold 6248.
The VM uses an explicit `en-us` VNC keymap. Automated console input still lost
shifted characters after this setting was applied. Manual typing worked.
Direct `sendkey` commands in the Proxmox Monitor provided reliable shifted input.
The playbook requires the TSC clock source. It does not run the upstream host
installer, change KVM module parameters, change boot settings, disable GPU
drivers, alter APT repositories, or reboot the host. If macOS fails to boot,
inspect the console and KVM logs before considering host changes.

## Install macOS

Use the signed-in [Proxmox page](https://pve.wbreiler.com), select Atlas,
and open VM 108's console.

1. Start VM 108 and open its Proxmox console.
2. Select the recovery image in OpenCore.
3. Open Disk Utility and select **View > Show All Devices**.
4. Erase only the new 128 GiB virtual disk as APFS with a GUID partition map.
5. Close Disk Utility and install macOS on that disk.

During installation, select **macOS Installer** in OpenCore after each restart.
After installation, select the installed macOS disk. Keep the OpenCore ISO
attached because it supplies the bootloader. Keep SIP and Gatekeeper enabled.
This VM has no GPU passthrough. Desktop performance and graphics features are
limited by its virtual display. Unique SMBIOS identity and Apple account
integration are outside this initial installation.

The existing all-guests PBS job includes VM 108. That job protects the VM disks,
but not the ISO files on `local`. Preserve the pinned OpenCore ISO and recovery
image separately for disaster recovery. Automatic host startup stays disabled.

## Verification on 2026-10-23

VM 108 booted into the **Reinstall macOS Tahoe** recovery screen on Atlas.
The host retained `ignore_msrs=N`. Repository-wide `ansible-lint`, syntax checks,
and the deployment repeat run passed (`changed=0`). A check-mode attempt with
unrelated VM ID 122 failed at the identity guard with zero changes, as expected.
The new disk was initialized as an APFS volume named `macos`. After explicit
user authorization, Apple's license was accepted and installation started on
that volume. Account setup and desktop checks remain pending. Installation
progress alone does not prove those steps. DHCP requests left Atlas without an
offer. The approved `10.10.40.9` reservation was saved on Arista. Recovery
networking was configured through `scutil --prefs`: the existing
Ethernet service uses Manual IPv4, address `10.10.40.9/24`, router `10.10.40.1`,
and DNS server `192.168.1.1`. After committing and applying those preferences,
`curl -I https://www.apple.com` returned HTTP 200 with certificate verification
enabled. These Recovery preferences have not been verified across a restart or
in the installed OS.

During installation preparation, Forgejo held 219 unintended secondary IPv4
addresses. After approval, those addresses were removed while its primary
`10.10.40.38` and API service remained available. The recovery snapshot is on
Prometheus at `/root/forgejo-ipv4-before-macos-20261023.json`, with routes in
`/root/forgejo-routes-before-macos-20261023.json`. The address count remained one
on subsequent checks. Forgejo's filesystem was full. No files were deleted and
no services were restarted. The cause of the secondary addresses remains
unconfirmed and the full filesystem needs separate attention.
