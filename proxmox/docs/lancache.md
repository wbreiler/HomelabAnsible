# LANCache on a Proxmox SSD

Terraform owns the Debian VM and its disks. The guest playbook installs Docker,
mounts the disposable disk, and runs the pinned cache, DNS, and manager images.
An additional pinned HAProxy container pools upstream HTTP/1.1 connections.
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
lancache_worker_dns_ip: 172.30.0.10
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

## Uncached downloads

The internal nginx redirect handler uses HTTP/1.1 and normalizes full upstream
responses into the requested byte ranges. This prevents an origin that ignores
`Range` from truncating a sliced download. The outer cache retains its original
1 MiB slices and cache keys, so existing cached games remain usable.
The disk cache also uses HTTP/1.1 and a keepalive pool to reach the local
redirect handler. Keep both proxy hops pooled. Reopening the local connection
for every slice can reduce uncached throughput even when WAN connections reuse.

The `upstream` container listens only on loopback inside the cache's network
namespace. It pools connections by CDN host and address. Each persistent
connection retains its resolved address until the host changes or an upstream
error requires another lookup. Private destination addresses are rejected.

Steam depot chunks have an additional 256 MiB RAM buffer with a five-second
lifetime and an 8 MiB object limit. Adjacent disk-cache slices can share one
complete WAN fetch. This buffer does not spill to disk. When it is full, requests
fetch from the origin. The outer cache still writes its normal disk slices.
Explicit `nocache` requests bypass this buffer and retain upstream range requests.
Other download paths retain their upstream range requests. HTTPS passthrough
and the dashboard database are unchanged.

The final startup hook installs the nginx configuration after the image edits
its stock files. Do not mount over those stock files, since the image uses
atomic replacements during startup. Ansible includes the hook and configuration
checksums in Compose labels so changes recreate the affected containers and
remount updated files. Keep DNS and
the upstream container attached to the current monolithic network namespace.
After changes, require a second playbook run with zero changes.

For a regression check on a Docker host with the pinned cache image available:

```sh
python3 tests/lancache_proxy_integration.py /opt/lancache/nginx-upstream.conf /opt/lancache/nginx-cache-upstream.conf /opt/lancache/upstream-hook.sh 'lancachenet/monolithic@sha256:155817065b13cc427aa0014acc34bbb389591400d7639c95abcfcfb2230ad7f0'
```

This isolated test checks real image startup, complete downloads, byte ranges,
and redirects against an origin that deliberately ignores ranges. It also
verifies that adjacent slices reuse one local proxy connection. For performance validation, use a
wired client, verify that every selected chunk is absent before the first pass,
and compare uncached, cached, and direct transfers with byte counts and hashes.
Do not use `nocache` queries as a substitute for a fresh workload.

## Automatic game updates

Use LANCache Manager's native **Management → Schedules → Scheduled Prefill**.
It checks game manifests and downloads updates into LANCache. Clients must still
use LANCache DNS and install updates through their launchers. This does not
install games on client computers.

1. Start a persistent session for each required platform. Sign in to Steam or
   Epic through the manager. Riot does not require a login.
2. Select and save the exact games. A nonempty selection overrides the **All**
   preset. An empty selection with **All** can download the whole library.
3. Enable the platform and set its interval to **1 hour**. Leave **Force
   re-download** disabled. Select the required Steam operating systems.
4. Select **Full persistence** for each enabled platform. This preserves its
   login across a manager restart and permits recovery after an involuntary
   worker or VM shutdown. An explicit session stop still clears its login.
5. Use **Run Now** for the initial fill. Verify a completed run, cache traffic,
   and a next-run time. A saved schedule starts one interval after saving.

The manager prevents overlapping runs on the same platform and skips a busy
or unauthenticated session. Different platforms can run concurrently.
The interval runs from the previous attempt's completion. A long fill
can delay the next check. The initial fill can be large. Cache capacity and
eviction still apply, so older chunks may need another WAN fetch.
For shared SSD storage, start with a fixed concurrency of eight per platform.
Increase it only after checking latency during a host backup and a bulk fill.
This setting limits automatic prefill workers, not normal client downloads.

The role pins the Steam, Epic, and Riot daemon images by digest and supplies
the worker network and cache addresses. Its separate `worker-dns` container
returns the bridge cache address. Public DNS continues to return the public
macvlan address. Workers cannot reach that public address through the guest,
so do not configure their DNS to use the public-facing DNS instance. Steam's
explicit cache override can hide this error until Epic or Riot is tested.

The manager pin uses upstream's
development build at revision `348dbcf551175f309693b89695bd1bd472cbbb42`.
The published `v1.10.6` manager cannot start these protocol 2 workers. Treat
the manager and worker pins as a compatible set. Do not return the manager
to the stable tag without compatible workers and migration validation.

Before a manager upgrade, back up the stopped dashboard and the persistent
worker login volumes privately. Test database migration on a separate copy,
without network access or a Docker socket. Compare download byte totals and
account records, not only row counts. Newer managers can consolidate download
sessions while retaining the same bytes and history range. Rollback can require
restoring the database backup as well as the previous image.

The embedded PostgreSQL server has ten minutes to recover after an unclean
shutdown. Bulk cache writes can overlap host backups and exceed its default
60-second startup allowance. The image starts PostgreSQL with `su -`, so the
role supplies `PGCTLTIMEOUT` through PAM's `/etc/environment`. A Docker environment
variable alone does not survive that login shell. The playbook waits for the
dashboard health check as well as cache readiness.

Database commands allow 120 seconds for a durable commit during storage
contention. The default 30-second timeout can make EF retry an insert that
already committed, causing duplicate session IDs and a failed login. Keep
database durability and authentication enabled. Do not delete sessions or
reset credentials to address this failure. Database credentials still come
from the private environment file. After an upgrade, test an actual sign-in
as well as `/health`. A new authentication setup screen can require the owner
to confirm the existing API-key-and-password mode.

The manager owns worker lifecycle,
account sessions, selected games, and schedules. Keep these in its backed-up
state, not tracked Ansible variables. Do not add a second cron scheduler or
overwrite the user's selections during a playbook run. Preserve Docker named
volumes on the system disk because they contain persistent platform logins.

Platform sessions can expire or be revoked. The manager reports when another
sign-in is required. A running container alone does not prove authentication.
Verify live login status or a successful prefill. Do not reset manager account
credentials or print API keys to automate this setup.

Prefer the authenticated manager UI or API for schedule changes. Its API key
alone does not authorize account routes. If host-level recovery requires an
offline state edit, stop only the dashboard, back up its state privately,
preserve unrelated fields and file ownership, and restart the dashboard.
Never edit its cached state file while the process is running. Verify that
the manager reconnects to each persistent worker without another login.

See the [upstream prefill guide](https://regix1.github.io/lancache-manager/prefill/)
for the current interface. Validate behavior against the pinned manager version
before an upgrade.
