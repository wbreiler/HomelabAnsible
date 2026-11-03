# UniFi and PXE network boot

The existing netboot.xyz guest serves bootloaders through `tftpd-hpa` from
`/srv/tftp`. Terraform owns its hardware and network interface. Verify its
current address, DHCP reservation, boot-file checksums, and service before
changing DHCP. Updating network boot does not require a guest or firmware upgrade.

UEFI x86-64 uses `netboot.xyz.efi`; legacy BIOS uses `netboot.xyz.kpxe`.
UniFi exposes one filename per network. A UEFI-only configuration does not
support legacy BIOS or ARM64 firmware. The standard loader configured here
does not install the separate [Secure Boot shim chain](https://netboot.xyz/docs/faq/#does-netbootxyz-support-secure-boot).
Use it with Secure Boot disabled. Internet access is needed to download its menu
and selected images. Network boot displays a menu; it does not select an
installer or overwrite a disk automatically.

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
