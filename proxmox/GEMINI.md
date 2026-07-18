# Gemini Context: Proxmox Ansible Automation

This project contains Ansible playbooks and roles for automating the deployment and management of a Proxmox VE cluster. It handles repository configuration, cluster formation, backup storage (PBS), and ISO management. Monitoring is handled by a Prometheus + Grafana LXC stack.

## Project Structure

*   **`site.yml`**: The main entry point playbook. Orchestrates the execution of roles.
*   **`inventory.yml`**: (Gitignored) Defines the Proxmox hosts (IPs, names). See `inventory.yml.example`.
*   **`group_vars/proxmox_cluster.yml`**: (Gitignored) Cluster-wide configuration and secrets (often Vault-encrypted). See `group_vars/proxmox_cluster.yml.example`.
*   **`host_vars/`**: (Gitignored) Per-host configuration, specifically for PBS namespaces. See `host_vars/example.yml`.
*   **`roles/`**: Contains the logic for specific tasks:
    *   `configure_repos`: Sets up Proxmox repositories (disables enterprise, enables no-subscription).
    *   `cluster_setup`: Creates or joins a Proxmox cluster.
    *   `pbs_storage`: Configures Proxmox Backup Server storage with shared namespace.
    *   `manage_isos`: Downloads or mounts ISOs.
    *   `update_all`: Updates Proxmox host nodes and LXC operating-system packages via apt or apk.
    *   `pbs_restore`: Restores LXC containers from PBS backups.
*   **`ansible.cfg`**: Project-specific Ansible configuration.

## Setup & Configuration

1.  **Prerequisites**:
    *   Python 3.
    *   Ansible.
    *   SSH access to target Proxmox nodes.

2.  **Dependencies**:
    Install required collections:
    ```bash
    ansible-galaxy collection install -r requirements.yml
    ```

3.  **Configuration Files**:
    *   Copy `inventory.yml.example` to `inventory.yml` and populate it.
    *   Copy `group_vars/proxmox_cluster.yml.example` to `group_vars/proxmox_cluster.yml`. Configure secrets (PBS credentials) and features.
    *   Create `host_vars/<node_name>.yml` for each node to define PBS configuration.

## Usage

### Running the Playbook
Run the full site setup:
```bash
ansible-playbook site.yml
```

If using Ansible Vault for `group_vars`:
```bash
ansible-playbook site.yml --ask-vault-pass
```

### Tags
Use tags to run specific parts of the automation:
*   `repos`: Configure repositories only.
*   `cluster`: Run cluster setup logic.
*   `pbs`: Configure PBS storage.
*   `isos`: Manage ISO downloads/mounts.
*   `update`: Update nodes and LXC containers (requires `-e 'run_updates=true'`).
*   `restore`: Restore containers from PBS backups (requires `-e 'restore_from_pbs=true'`).

Example:
```bash
ansible-playbook site.yml --tags "pbs,update"
ansible-playbook site.yml --tags update -e 'run_updates=true'
```

### Limiting Hosts
Run on specific nodes:
```bash
ansible-playbook site.yml --limit pve-node-1
```

## Development Conventions

*   **Secrets Management**: NEVER commit `inventory.yml`, `group_vars/proxmox_cluster.yml`, or `host_vars/*.yml`. Use the provided `.example` files for templates.
*   **Idempotency**: Ensure all tasks are idempotent. The `pbs_storage` role uses a specific "remove-then-add" pattern to ensure configuration updates are applied cleanly.
*   **Privilege Escalation**: The playbook runs with `become: true` by default (sudo to root).
*   **Testing**: Local testing logic is located in `tests/`.
*   **Linting**: Adhere to standard Ansible linting practices.

## Key Architectural Decisions

*   **PBS Namespace**: Storage configuration is cluster-wide; the shared namespace and username come from the cluster master's `host_vars`, the password from group_vars.
*   **Cluster Formation**: The master node creates the cluster; subsequent nodes join. Logic checks for existing cluster status to prevent errors.
*   **Ansible Config**: Host key checking is disabled (`host_key_checking = False`) for ease of use in this specific homelab environment. Fact caching is enabled.
*   **No Ceph or Tailscale**: This environment does not use Ceph or Tailscale VPN.
