# Ponytail Audit TODO

Findings from `/ponytail-audit`, biggest cut first.

## Bug review — priority order

- [x] **P0: Make PBS storage configuration cluster-safe.** `pvesm remove/add` updates the shared cluster storage configuration, but `pbs_storage` runs on every node with host-specific credentials and namespaces. Run the mutation once on a designated node and define a supported strategy for per-node PBS access; otherwise concurrent runs race and the last host's configuration wins.
- [x] **P0: Load `tcp_bbr` before applying BBR sysctl settings.** The network role sets `net.ipv4.tcp_congestion_control=bbr` before loading the kernel module, which fails on systems where BBR is not built in.
- [x] **P0: Restore the correct guest type when `force: true`.** `pbs_restore` always runs `pct stop/destroy` for an existing target, so forced restores of QEMU VMs fail. Detect the target type first and use `qm` for VMs.
- [x] **P1: Add VMID ranges to `inventory.yml.example`.** `vm_deploy` requires `vmid_range_start` and `vmid_range_end` for every cluster host, but the tracked inventory example omits them.
- [x] **P1: Remove duplicate VM deployment keys from `group_vars/proxmox_cluster.yml.example`.** The second `deploy_vms` and `vm_deploy_vms` declarations overwrite the first YAML mapping entries.
- [x] **P1: Use `network_tuning_storage_vlan_parent` in the VLAN existence check.** The role checks only `vmbr0.<vlan>`, while the created interface uses the configurable parent interface.
- [x] **P2: Correct the Atlas address in `inventory.yml.example`.** It is `10.10.30.4` in the example but `10.10.30.9` in the project documentation.

## Security hardening (2026-07-14)

- [x] Removed dead `netdata` role (curl-piped remote installer, bound to all IPs)
- [x] LXC bootstrap defaults to unprivileged; privileged only when NFS is required (`tasks/create_lxc.yml`)
- [x] Pinned `discoverr_bot` to a commit SHA and `stash` to a release tag; override vars to bump
- [x] Cluster join password moved off the pvecm command line via `ansible.builtin.expect`

## Remote installer migration — complete

All apps migrated to repository-owned managed roles: IP-Tag, Apt-Cacher NG, Prowlarr, Homebridge, Spoolman, Gitea Mirror, Seerr, Pocket ID, Forgejo, Sonarr, and Radarr. The generic remote-installer path has been removed.

Follow-up when desired: step Forgejo up one major at a time (13.0.4 → 14.0.5 → 15.0.5 → 16.0.0), reviewing each major's release notes before bumping `forgejo_version` and its checksum.

## Completed ponytail audit items

- [x] Extract shared LXC bootstrap (create/start/wait/SSH key/NFS) into `tasks/create_lxc.yml`; update `gallery_dl` and `stash` to use it (~-120 lines)
- [x] Remove `gallery_dl_cookies_arg` `set_fact`; inline cookie-flag condition in `gallery-dl.sh.j2`
- [x] Remove duplicate `Ensure cookies config dir` task inside cookies block in `gallery_dl/tasks/main.yml` (already done unconditionally above it)
- [x] Reorganize `pbs_restore` set_facts: `backup_volid` alone in task 1, then `is_vm`/`type`/`cmd` derived from it in task 2
- [x] Remove `ubuntu-26.04-standard` from `download_templates/defaults/main.yml` (doesn't exist yet)
