# Gemini Context: Proxmox Ansible Automation

This project manages the two-node `cluster-nash` Proxmox VE 9 cluster and
its PBS integration. The canonical implementation and operating guidance is
in [`AGENTS.md`](AGENTS.md); read it before making changes. Human-oriented
setup and role documentation is in [`README.md`](README.md). Role-specific
implementation notes are consolidated in [`AGENTS.md`](AGENTS.md).

## Current architecture

- Terraform owns guest provisioning/hardware, backup jobs, HA policy, the PBS
  connection, and cached media. Ansible configures existing running guests.
  Legacy provisioning and platform-role entry points refuse execution.
- Run Ansible from this directory so `ansible.cfg`, the ignored inventory,
  and the configured SSH-agent identity are used (`~/.ssh/cluster.pub` on the current controller).
- `site.yml` first configures `proxmox_cluster`, then applies
  `network_tuning` to `proxmox_cluster:pbs_nodes`.
- The repository has no Ceph automation. Tailscale exists only as the opt-in
  `tailscale_router` LXC; it is not installed on cluster nodes.
- Managed app roles are repository-owned, version-pinned, and
  checksum-verified. Gatus and Diun are the opt-in monitoring roles.
  Guarded LXC update services preserve backup, version, age, and retry checks.
- Private HTTPS/DNS and Homebridge discovery use separate playbooks.
  NexDeck board edits remain in its database. Follow the guides linked in
  `AGENTS.md` before changing these integrations.
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
