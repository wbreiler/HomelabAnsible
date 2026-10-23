# PVE cluster and PBS system report

Collected: **2026-10-22 19:28:49 CDT** (2026-10-23T00:28:49.207294+00:00).

Live, read-only SSH queries covered `cluster-nash` and PBS `mnemosyne`. Both PVE nodes were online, and the cluster had quorum. Hardware and memory queries ran within seconds of one another. CPU utilization came from separate one-second samples shortly afterward.

## CPUs and RAM

RAM values use GiB (2³⁰ bytes). Total means memory visible to Linux, after hardware and kernel reservations. Used RAM equals `MemTotal − MemAvailable`. Available RAM includes memory that Linux can reclaim. Host memory includes guest workloads and host services.

| Host | Role | CPU model | Sockets | Cores | Threads | CPU busy | RAM total GiB | RAM used GiB | RAM used % | RAM available GiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prometheus | PVE | Intel(R) Xeon(R) CPU E5-2697A v4 @ 2.60GHz | 2 | 32 | 64 | 0.3% | 377.74 | 28.62 | 7.6% | 349.11 |
| atlas | PVE | Intel(R) Xeon(R) Gold 6248 CPU @ 2.50GHz | 2 | 40 | 80 | 0.4% | 376.50 | 57.93 | 15.4% | 318.58 |
| mnemosyne | PBS | Intel(R) Xeon(R) CPU E3-1220 v5 @ 3.00GHz | 1 | 4 | 4 | 0.5% | 62.75 | 32.55 | 51.9% | 30.21 |

| Scope | Sockets | Cores | Threads | RAM total GiB | RAM used GiB | RAM available GiB |
| --- | --- | --- | --- | --- | --- | --- |
| PVE cluster | 4 | 72 | 144 | 754.24 | 86.55 | 667.69 |
| PBS | 1 | 4 | 4 | 62.75 | 32.55 | 30.21 |
| All hosts | 5 | 76 | 148 | 817.00 | 119.10 | 697.90 |

No swap is configured on these hosts. CPU busy excludes idle time and I/O wait. These samples do not describe peak or average daily use.

## ZFS pools

This table reports `zpool list` capacity in TiB (2⁴⁰ bytes). RAIDZ figures include parity space. Dataset and datastore capacity below better describe application space.

| Host | Pool | Topology / nominal disk sizes | Pool size TiB | Allocated TiB | Free TiB | Allocated % | Health |
| --- | --- | --- | --- | --- | --- | --- | --- |
| prometheus | helios | Single 2 TB Crucial MX500 SSD | 1.812 | 0.321 | 1.492 | 17.7% | ONLINE |
| prometheus | rpool | Mirror: 2 × 200 GB Intel SSD | 0.180 | 0.047 | 0.133 | 26.1% | ONLINE |
| prometheus | tartarus | RAIDZ1: 3 × 1.2 TB Seagate HDD | 3.266 | 0.127 | 3.139 | 3.9% | ONLINE |
| atlas | helios | Stripe: 4 × 512 GB Micron SSD | 1.859 | 0.561 | 1.298 | 30.2% | ONLINE |
| atlas | rpool | Mirror: 2 × 250 GB Samsung SSD | 0.225 | 0.045 | 0.179 | 20.1% | ONLINE |
| atlas | tartarus | RAIDZ1: 3 × 1.2 TB Seagate HDD | 3.266 | 0.127 | 3.139 | 3.9% | ONLINE |
| mnemosyne | mneme | Stripe: 3 × 2 TB Seagate HDD | 5.438 | 0.696 | 4.741 | 12.8% | ONLINE |
| mnemosyne | rpool | Mirror: 2 × 120 GB Intel SSD | 0.106 | 0.021 | 0.085 | 19.8% | ONLINE |

Each `helios`, `tartarus`, and `rpool` belongs to its host. Identical names on different hosts do not indicate shared storage. Disk sizes in topology descriptions use decimal GB/TB.

## PVE storage

These values come from each node’s PVE storage API. Used values can include snapshots and reservations. `local` and `local-zfs` share their host’s `rpool` capacity. Do not add their totals or free space.

| Host | Storage | Type | Total TiB | Used TiB | Available TiB | Used % | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| prometheus | helios | zfspool | 1.757 | 0.322 | 1.436 | 18.3% | Active |
| prometheus | local | dir | 0.158 | 0.031 | 0.127 | 19.4% | Active |
| prometheus | local-zfs | zfspool | 0.133 | 0.006 | 0.127 | 4.3% | Active |
| prometheus | tartarus | zfspool | 2.107 | 0.338 | 1.769 | 16.1% | Active |
| atlas | helios | zfspool | 1.817 | 0.679 | 1.137 | 37.4% | Active |
| atlas | local | dir | 0.203 | 0.030 | 0.172 | 15.0% | Active |
| atlas | local-zfs | zfspool | 0.176 | 0.004 | 0.172 | 2.2% | Active |
| atlas | tartarus | zfspool | 2.107 | 0.338 | 1.769 | 16.1% | Active |

## PBS storage

PBS version: **4.2.8-1**. Datastore `mneme` uses `/mneme` on the local ZFS pool `mneme`. Both PVE nodes expose this same datastore as shared storage `mnemosyne`. Count it once.

| Filesystem | Total TiB | Used TiB | Available TiB | Used % |
| --- | --- | --- | --- | --- |
| Backup datastore /mneme | 5.312 | 0.696 | 4.616 | 13.1% |
| PBS root / | 0.103 | 0.021 | 0.082 | 20.4% |

Filesystem totals reflect ZFS overhead and reserved space. They differ from the underlying pool figures. Backup capacity describes physical filesystem use, not the logical size of all retained backups.

## Storage observations

- All eight pools report `ONLINE`, with no known data errors. Their last reported scrubs completed on October 11, 2026, with zero errors.
- Prometheus `helios` uses one disk. Atlas `helios` and PBS `mneme` use stripes. These pools have no disk redundancy.
- Prometheus dataset `helios/subvol-103-disk-0` reports 100% filesystem usage and zero available bytes.
- Pool, dataset, and PVE figures overlap. No combined storage total is given because these views must not be added together.

## Sources and limits

Hardware: `lscpu -J` and `lsblk -b -J`. RAM: `/proc/meminfo`. CPU busy: two `/proc/stat` samples one second apart. Storage: `zpool list`, `zpool status`, `zfs list`, and `df -B1 -T -P`.

PVE: `/cluster/status`, `/nodes/<node>/status`, and `/nodes/<node>/storage` through `pvesh`. Both nodes report PVE Manager **9.2.21**. PBS: `proxmox-backup-manager versions`, `datastore list`, and the local status API. All hosts run kernel **7.0.14-20-pve**.

This report is a point-in-time snapshot. It does not test disk performance, SMART health, backup integrity, or restore success. No host configuration changed.
