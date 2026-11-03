# UniFi and PXE network boot

The existing netboot.xyz guest serves bootloaders through `tftpd-hpa` from
`/srv/tftp`. Terraform owns its hardware and network interface. Verify its
current address, DHCP reservation, boot-file checksums, and service before
changing DHCP. Updating network boot does not require a guest or firmware upgrade.

UEFI x86-64 uses the existing DHCP filename `netboot.xyz.efi`. The PXE role
installs the pinned [signed iPXE chain](https://ipxe.org/secboot) at that filename,
with its companion `ipxe.efi`, `shimx64.efi`, and `autoexec.ipxe`. This preserves
DHCP configuration while enabling Secure Boot. The original unsigned loader
remains at `netboot.xyz-unsigned.efi`. The application updater preserves the
managed signed entry point. Legacy BIOS uses `netboot.xyz.kpxe` separately.
UniFi exposes one filename per network. This configuration targets UEFI x86-64.

`autoexec.ipxe` requests `/boot/<machine-uuid>.ipxe` from the local HTTP server.
Terraform publishes this entry only for a declared installation VM. The installer
checks the UUID again before it partitions `/dev/sda`. After verification,
Terraform retires the automatic entry. Other machines receive the interactive
netboot.xyz menu, which needs Internet access. Menu selection is manual.

## Configure the existing PXE guest

Run from `proxmox/`. Use `pxe-inventory.yml.example` as an inventory template,
or add its guest group to the existing ignored `inventory.yml`. Keep real service
values in ignored `group_vars/pxe_guests.yml`, using its tracked example.
The guest must already exist and run. Terraform owns its disk capacity, network
interface, and lifecycle. This playbook installs only guest software.

```sh
ansible-playbook -i tmp/pxe-inventory.yml pxe-guests.yml --check --diff
ansible-playbook -i tmp/pxe-inventory.yml pxe-guests.yml
```

The role installs nginx, TFTP support, rsync, and the checksum-pinned signed
loader. It serves `/srv/pxe` on HTTP port 80. Terraform owns original ISOs under
`/srv/pxe/iso`, extracted installers under `/srv/pxe/images`, and per-VM files
under `/srv/pxe/install`. The service stores the ISO bytes locally. It does not
proxy them from the NAS. The HTTP library index is available at `/iso/`.

Follow the [Terraform guide](../../terraform/README.md#pxe-service-and-library)
to populate the library and deploy unattended VMs. The answer files contain
public SSH keys and network settings. Keep this service on trusted LANs and
never put passwords or private keys in these files. Secure Boot does not
authenticate HTTP answer files. Windows and other archived ISOs remain available
for download. The Terraform unattended profiles support Debian, Ubuntu Server,
and Fedora Server. Merely copying an arbitrary ISO does not make it PXE bootable.

## Routers without a usable next-server field

Some firmware ignores DHCP option 66 and requires the BOOTP `siaddr` field.
EOS 4.28 supplies options 66/67 but cannot set `next-server`. A successful
explicit-server TFTP test does not prove firmware boot support.

For these networks, `pxe_proxy_networks` enables dnsmasq in **proxy-only** mode.
The existing router still allocates every address. The proxy advertises the
signed bootloader and its server address to PXE clients. DNS service and packet
forwarding are disabled. No DHCP pool, gateway, or DNS-server setting moves.

Terraform must attach the PXE guest to each affected network first. Each added
interface needs an unused static address outside DHCP, with no additional default
gateway. Preserve the original interface, MAC, address, and route. Add only the
required interfaces. Do not extend switch trunks or alter router management paths.

Set these inventory variables after verifying the interface names and subnets:

```yaml
pxe_tftp_address: 192.0.2.10
pxe_proxy_networks:
  - {interface: eth0, network: 192.0.2.0, netmask: 255.255.255.0}
```

The role validates the dnsmasq configuration and runs a dedicated `pxe-proxy`
service on UDP 67/4011. It does not use dnsmasq for TFTP. TFTP binds the
advertised primary address so replies retain that address on every interface.
Keep that address static or reserved in DHCP. Validate a real UEFI
boot and capture DHCP replies to confirm that only the router supplies leases.
See the [dnsmasq proxy documentation](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).

## DHCP ownership

Discover the current owner of each subnet before changing it. UniFi networks
marked as externally routed do not serve DHCP, even if old DHCP fields remain
in their records. Configure their actual router instead. The limited Arista
workflow is documented in [arista/README.md](../../arista/README.md#network-boot).

The UniFi helper rejects externally routed networks, relay networks, disabled
networks, duplicate targets, and disabled DHCP without an explicit address range.
If adding DHCP, verify all static addresses and reservations first. A silent ping
does not prove that a disconnected device has no static address. Preserve existing
gateways and routing; no DHCP relay is needed when the router already serves DHCP.

## UniFi preview and application

Save the Network API key in a mode-0600 file outside Git. The helper uses the
controller's network configuration API with the integration key. Credentials
travel through verified SSH stdin and never appear in argv or gateway files.
It uses partial updates so unrelated network fields stay intact.

Create a deployment JSON in ignored `proxmox/tmp/`, using verified addresses:

```json
{
  "server": "192.0.2.10",
  "filename": "netboot.xyz.efi",
  "networks": [{"vlan": 1}, {"vlan": 70}]
}
```

An explicitly reviewed new pool uses `"dhcp_range": ["START", "STOP"]` on its
network entry. Never include an existing static address or the gateway in it.

Run from `proxmox/`:

```sh
python3 -m unittest discover -s tests -p test_unifi_pxe.py
python3 files/unifi_pxe.py \
  --ssh-target root@GATEWAY_ADDRESS --identity-file ~/.ssh/cluster.pub \
  --key-file /private/tmp/homelab-unifi-api-key --config tmp/pxe-unifi.json
```

Review the displayed fields, then repeat with `--apply`. The helper saves a
root-only snapshot under `/data/homelab-backups/pxe-TIMESTAMP/` before writing.
It verifies that the complete returned network differs only by the intended
fields. Unexpected readback or concurrent edits stop the run. Earlier successful
updates remain applied after a later failure. Inspect the snapshot and live
settings before retrying. A repeat preview must show `"changes": []`.

For recovery, use the protected snapshot to restore only fields listed in
`changes.json` through the same controller API. Fields absent in the snapshot
need to be cleared through the controller. Do not write MongoDB or generated
dnsmasq files. Remove the temporary API key file when finished.

## Verification

Check the generated DHCP boot settings, actual DHCP offers, complete TFTP file
transfers and checksums, and firmware boot. TFTP starts at UDP 69 but transfers
use a server-selected UDP port; a firewall rule for only UDP 69 is insufficient
without working TFTP connection tracking. Preserve VLAN isolation and permit
only required PXE traffic where an exception is needed.

Test each VLAN from an attached client. A gateway-originated transfer proves
reachability but does not prove client forwarding or DHCP broadcast reception.
A VLAN defined only on UniFi cannot carry clients through a switch trunk that
does not include it. Do not change protected trunks as part of this workflow.
