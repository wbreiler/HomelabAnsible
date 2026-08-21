# Gemini Context: Proxmox Ansible Automation

This project manages the three-node `cluster-nash` Proxmox VE 9 cluster and
its PBS integration. The canonical implementation and operating guidance is
in [`AGENTS.md`](AGENTS.md); read it before making changes. Human-oriented
setup and role documentation is in [`README.md`](README.md). Role-specific
implementation notes are consolidated in [`AGENTS.md`](AGENTS.md).

## Current architecture

- Run Ansible from this directory so `ansible.cfg`, the ignored inventory,
  and the `~/.ssh/cluster-nash` identity are used.
- `site.yml` first configures `proxmox_cluster`, then applies
  `network_tuning` to `proxmox_cluster:pbs_nodes`.
- The repository has no Ceph automation. Tailscale exists only as the opt-in
  `tailscale_router` LXC; it is not installed on cluster nodes.
- Managed app roles are repository-owned, version-pinned, and
  checksum-verified. Gatus and Diun are the opt-in monitoring roles.
- Actual inventory, group variables, host variables, credentials, and
  gallery-dl cookies are ignored. Commit only their sanitized examples.
- Shared Proxmox cluster mutations run through the designated cluster master.
  Destructive cleanup and restore paths remain explicitly gated.

## Validation and commits

```bash
ansible-lint
ansible-playbook -i inventory.yml site.yml --syntax-check
git diff --check
```

Use `<scope>: <imperative summary>` for commits. Commit completed, validated
work in this project as one scoped commit, and never push; the user pushes.
