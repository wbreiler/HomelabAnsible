# macOS Tahoe on Atlas

`macos.yml` creates VM 108 (`macos-tahoe`) on Atlas with 8 cores, 32 GiB RAM,
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
user authorization, Apple's license was accepted and installation completed on
that volume. The VM restarted automatically and reached Setup Assistant.
The user created the local account and approved the separate Setup Assistant
license acceptance. Central Time is selected. Location services and diagnostic
sharing are disabled, and Screen Time is deferred. The user explicitly approved
continuing without FileVault. The VM disk is not encrypted by FileVault.
The final automatic-update screen stalled and did not respond to keyboard or
menu input. A graceful VM shutdown timed out. Resetting only VM 108 recovered
the guest, which automatically booted the installed disk and reached the local
account login screen. The user signed in and the desktop opened.
`sw_vers` reports macOS 26.7.1, build 25G241. SIP and Gatekeeper are enabled.
`fdesetup status` confirms FileVault is off, as approved. Application launches
are slow and the desktop background renders white through the virtual display.
DHCP requests left Atlas without an offer. The approved `10.10.40.9` reservation was saved on Arista. Recovery
networking was configured through `scutil --prefs`: the existing
Ethernet service uses Manual IPv4, address `10.10.40.9/24`, router `10.10.40.1`,
and DNS server `192.168.1.1`. After committing and applying those preferences,
`curl -I https://www.apple.com` returned HTTP 200 with certificate verification
enabled. Setup Assistant required the same manual IPv4, router, and DNS
configuration in the installed OS. After applying it, the installed OS answered
three pings with zero loss. Arista confirmed `10.10.40.9` belongs to
`BC:24:11:20:25:AA`. After the restart, the address and router persisted, but
the Ethernet service had no saved DNS server. The installed desktop was corrected
with `networksetup -setdnsservers Ethernet 192.168.1.1`. Reading that setting
confirmed the saved server. A guest `curl -I https://www.apple.com` returned
HTTP/2 200 with certificate verification enabled. After the resource upgrade and a full VM power cycle, the saved DNS server
remained `192.168.1.1` and certificate-checked HTTPS again returned HTTP/2 200.

The existing VMXNET3 adapter supports a `10Gbase-T` full-duplex media mode.
macOS currently reports `autoselect (1000baseT <full-duplex>)`. This is a guest
link label, not a measured throughput result. Physical NIC passthrough was
not performed.

## Homebrew and network baseline on 2026-10-23

Homebrew 7.0.10 and iperf3 3.22 are installed for the local `pve` account.
The current installer rejects Intel macOS. The official Intel-compatible
installer revision `f4aa1b1ca5b256954dbde0315455fb259cdfc45a` installed current
Homebrew under `/usr/local`. Apple Command Line Tools 26.6 are installed.
Homebrew analytics are disabled, and `.zprofile` contains its shell environment.
Intel macOS is a Tier 3 Homebrew configuration. OpenSSL 4.0.3 and iperf3
required source builds.

Two 10-second, single-stream TCP tests used Mnemosyne at `10.10.20.2:5201`,
with the original 4-vCPU, 8-GiB allocation. Upload received 3.89 Gbit/s at the
server. Reverse download received 890 Mbit/s in macOS (893 Mbit/s at the
sender). These results do not establish a 10-Gbit/s maximum, but upload
exceeded the guest media label.
The approved temporary server firewall rule allowed only `10.10.40.9` to TCP
5201. The rule and temporary listener were removed and their absence verified.

After the tests, Atlas had about 312 GiB available RAM and 40 physical cores.
VM 108 was configured for 8 vCPUs and 32 GiB RAM. The previous VM configuration
is saved on Atlas at `/root/macos108-before-resources-20261023.conf`.
The guest shut down through its Apple menu after the host ACPI request timed
out. Proxmox started the VM with the new allocation and macOS returned to its
desktop. Guest `sysctl` confirmed `hw.ncpu: 8` and `hw.memsize: 34359738368`.
No disk, CPU model, network, or other guest allocation was changed. Lint and
syntax checks passed. A repeat deployment completed with `changed=0`. The
network test has not been repeated with the larger allocation.

During installation preparation, Forgejo held 219 unintended secondary IPv4
addresses. After approval, those addresses were removed while its primary
`10.10.40.38` and API service remained available. The recovery snapshot is on
Prometheus at `/root/forgejo-ipv4-before-macos-20261023.json`, with routes in
`/root/forgejo-routes-before-macos-20261023.json`. The address count remained one
on subsequent checks. Forgejo's filesystem was full. No files were deleted and
no services were restarted. The cause of the secondary addresses remains
unconfirmed and the full filesystem needs separate attention.
