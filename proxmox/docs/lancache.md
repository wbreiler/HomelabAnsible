# LANCache on a Proxmox SSD

Terraform owns the Debian VM and its disks. The guest playbook installs Docker,
mounts the disposable disk, and runs the pinned cache, DNS, and manager images.
Use a static management IP and two separate macvlan service addresses on the
VM's VLAN. Confirm address reservations and live ownership before deployment.

## Configure

1. Add the VM to the ignored Terraform `iso_installations` map. Select PXE,
   UEFI, Secure Boot, an SSD datastore, and a backed-up system disk. Set
   `cache_disk_gb` for the separate disk. Review the saved creation plan.
2. Add the verified VM to `lancache_guests` in the ignored Proxmox inventory.
   Use the pinned installed-host key and non-root installer account.
   Set the variables below in ignored host variables.
3. From `proxmox/`, run `ansible-playbook lancache-guests.yml` with
   `lancache_phase: prepare`. The role checks the hostname, disk serial, size,
   signatures, and mount location before it initializes an empty disk.
4. Seed the cache while the source is online. Preserve numeric ownership
   for the dashboard database and logs. Copy the final database only after
   the source dashboard has stopped. Store its credentials and sessions on
   the backed-up system disk. Protect all transfers and backups.
5. Set `lancache_phase: cache` to test the staged cache and DNS. After cutover,
   set `lancache_phase: full` and run the playbook twice. The second run should
   report zero changes.

Example host variables:

```yaml
terraform_guest_name: lancache-example
lancache_subnet: 192.0.2.0/27
lancache_gateway: 192.0.2.1
lancache_upstream_dns: 192.0.2.1
lancache_cache_ip: 192.0.2.11
lancache_dashboard_ip: 192.0.2.14
lancache_worker_subnet: 172.30.0.0/24
lancache_worker_cache_ip: 172.30.0.2
lancache_worker_dashboard_ip: 172.30.0.3
lancache_disk_gib: 768
lancache_cache_gib: 640
lancache_free_gib: 100
lancache_phase: prepare
```

## Cutover and recovery

Test on unused temporary addresses first. From a separate wired client, compare
a set of real cache hits against the old host. Send Steam's HTTP user agent.
Verify the returned byte lengths and the HIT response header. Check private DNS
forwarding, TCP/UDP DNS, and HTTPS passthrough.

Measure sustained writes with the node's regular replication workload active.
Check disk latency and other guests during the bulk copy. Run long transfers
as server-side jobs so a sleeping controller cannot interrupt them.

Stop staged cache writers before the final sync. Stop the old dashboard and
cache through TrueNAS middleware. Copy the final cache delta, logs, and stopped
dashboard state. Start the VM services on the original service addresses.
Verify dashboard history and worker DNS as well as client traffic. Set
`lancache_hosting: proxmox` in the old TrueNAS host variables to guard its
deployment playbooks. Standalone prefill workers can still use the public
cache address from the NAS.

For rollback, stop the VM's Compose project and verify that its service
addresses have been released. Restore the TrueNAS hosting selection. Start
the original cache and then its dashboard through middleware. Preserve both
copies. Rolling back after new dashboard writes requires reconciling the
newer dashboard state first.

PBS includes the system disk with the dashboard database, credentials and
logs. The cache disk has backup and replication disabled. After restoring
the VM, provision its cache disk before starting the stack. A restored
cache can refill through normal requests. The manager uses nginx's UID so
it can read the mode-0600 game chunks on the Linux filesystem.
