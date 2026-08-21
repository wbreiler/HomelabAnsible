# Proxmox Backup Server Ansible Configuration

Configures an existing Proxmox Backup Server with a local ZFS datastore, PBS
users, optional pull-style sync jobs, and Tailscale. It does not install the
PBS product or create/reconfigure the underlying ZFS pool.

## Features

- ✅ Removes stale PBS/Proxmox enterprise and no-subscription source files
- ✅ Uses an existing local ZFS pool of any size or vdev topology
- ✅ Creates a dedicated ZFS dataset with `atime=off`
- ✅ Creates missing PBS users and grants datastore-wide administrator access
- ✅ Configures MainStore on the local ZFS dataset
- ✅ Optional remote plus pull-style sync-job creation
- ✅ Installs and configures Tailscale VPN

## Prerequisites

- Existing PBS host on Debian 12 Bookworm; repository URLs are Bookworm-specific
- ansible-core 2.16 through 2.21 installed on the control node
- Root or sudo access on target PBS server
- SSH key authentication for routine playbook runs
- A local ZFS pool created on the PBS server
- Python 3 on target hosts

## Quick Start

### 1. Clone and Configure

```bash
# From the monorepo root
cd pbs

# Install the tested controller and collection dependency ranges
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml

# Copy example files
cp inventory.yml.example inventory.yml
cp group_vars/pbs_servers.yml.example group_vars/pbs_servers.yml

# Edit inventory with your PBS server details
vim inventory.yml

# Edit configuration variables
vim group_vars/pbs_servers.yml
```

### 2. Encrypt Sensitive Data (Recommended)

```bash
# Create the ignored vault password file without exposing the secret in argv
install -m 0600 /dev/stdin .vault_pass
# Type the password, then press Ctrl-D

# Encrypt the group vars file
ansible-vault encrypt group_vars/pbs_servers.yml
```

### 3. Run the Playbook

```bash
# Run all roles with SSH key authentication
ansible-playbook site.yml --vault-password-file .vault_pass

# Use password authentication only for an initial bootstrap, if required
ansible-playbook site.yml --vault-password-file .vault_pass --ask-pass

# Run with tags (specific roles only)
ansible-playbook site.yml --vault-password-file .vault_pass --tags pbs,users

# Skip specific roles
ansible-playbook site.yml --vault-password-file .vault_pass --skip-tags tailscale

# Dry run (check mode)
ansible-playbook site.yml --vault-password-file .vault_pass --check
```

## Directory Structure

```
pbs/
├── ansible.cfg                           # Ansible configuration
├── site.yml                              # Main playbook
├── requirements.txt                      # Tested ansible-core range
├── requirements.yml                      # Collection requirements
├── inventory.yml                         # Server inventory (DO NOT COMMIT)
├── inventory.yml.example                 # Example inventory
├── .gitignore                            # Git ignore rules
├── .vault_pass                           # Vault password (DO NOT COMMIT)
├── group_vars/
│   ├── pbs_servers.yml                  # Variables for PBS servers (DO NOT COMMIT)
│   └── pbs_servers.yml.example          # Example variables
├── roles/
│   ├── users/                           # User management role
│   │   ├── tasks/main.yml
│   │   └── defaults/main.yml
│   ├── pbs/                             # Datastore and sync-job configuration
│   │   ├── tasks/main.yml
│   │   ├── defaults/main.yml
│   ├── cleanup_repos/                   # Removes stale PBS/Proxmox repo files
│   └── tailscale/                       # Tailscale installation role
│       ├── tasks/main.yml
│       └── defaults/main.yml
└── README.md
```

## Configuration

### Inventory Configuration

Edit `inventory.yml`:

```yaml
all:
  children:
    pbs_servers:
      hosts:
        pbs-nash:
          ansible_host: 10.0.0.xxx  # Your PBS server IP
      vars:
        ansible_user: root
        ansible_python_interpreter: /usr/bin/python3
```

### Group Variables

Edit `group_vars/pbs_servers.yml`:

```yaml
# User Passwords
users_root_password: "your_secure_password"

users_pbs_users:
  - name: pbs-nash
    comment: "PBS Nash User"
    password: "secure_password"

# Local ZFS datastore
pbs_zfs_pool: "backup"
pbs_zfs_dataset: "backup/pbs"
pbs_zfs_create_dataset: true
pbs_datastore_path: "/mnt/datastore"
pbs_namespaces: []
pbs_namespace_password: ""  # Required when pbs_namespaces is not empty

# Pull-style sync job (runs weekly on Saturday at 11:30 PM)
pbs_configure_sync_job: true
pbs_sync_remote_fingerprint: "CHANGE_ME_remote_fingerprint"
pbs_sync_schedule: "sat 23:30"
```

## Roles

### users

Creates missing PBS users, grants `DatastoreAdmin` at `/datastore`, and can set
the root Unix password. An existing PBS user's password is not rotated because
the create command treats `already exists` as unchanged.

**Tags:** `users`, `setup`

**Variables:**

- `users_pbs_users`: List of users to create (default: empty; placeholder passwords are rejected)
- `users_root_password`: Root user password

### pbs

Waits for an already installed PBS service, validates or creates the datastore
dataset, registers the datastore, and optionally creates a remote and
pull-style sync job. Existing remotes/jobs are accepted as already present;
their settings are not reconciled by this implementation.

**Tags:** `pbs`, `setup`

**Variables:**

- `pbs_datastore_name`: Datastore name (default: `MainStore`)
- `pbs_zfs_pool`: Existing local pool containing the datastore dataset
- `pbs_zfs_dataset`: Dataset dedicated to PBS (default: `<pool>/pbs`)
- `pbs_zfs_create_dataset`: Create that dataset when it is absent
- `pbs_datastore_path`: Dataset mountpoint and PBS datastore path
- `pbs_namespaces`: Optional namespaces to create
- `pbs_namespace_password`: PBS repository password used for namespace creation
- `pbs_configure_sync_job`: Create the remote and sync job
- `pbs_sync_remote_fingerprint`: TLS fingerprint for the remote PBS
- `pbs_sync_schedule`: Sync schedule (e.g., `"sat 23:30"`)

### tailscale

Installs and configures Tailscale VPN (optional).

**Tags:** `tailscale`

**Variables:**

- `install_tailscale`: Enable the role from `site.yml` (default: `true`)
- `tailscale_auth_key`: Optional auth key; when non-empty it is passed through
  a mode-`0600` temporary file and removed afterward

## Usage Examples

### Run Specific Roles

```bash
# Only configure local storage and PBS
ansible-playbook site.yml --tags storage,pbs

# Only manage users
ansible-playbook site.yml --tags users

# Everything except Tailscale
ansible-playbook site.yml --skip-tags tailscale
```

### Working with Ansible Vault

```bash
# Encrypt a file
ansible-vault encrypt group_vars/pbs_servers.yml

# Decrypt a file
ansible-vault decrypt group_vars/pbs_servers.yml

# Edit encrypted file
ansible-vault edit group_vars/pbs_servers.yml

# View encrypted file
ansible-vault view group_vars/pbs_servers.yml

# Run with the ignored local vault password file
ansible-playbook site.yml --vault-password-file .vault_pass
```

### Check Mode (Dry Run)

```bash
# See what would change without making changes
ansible-playbook site.yml --check

# Check with diff output
ansible-playbook site.yml --check --diff
```

## Post-Installation

### 1. Access PBS Web Interface

Navigate to: `https://your-pbs-server:8007`

Default credentials:

- Username: `root`
- Password: (the one you set in group_vars)

### 2. Configure Tailscale

SSH to your PBS server and authenticate:

```bash
ssh root@pbs-server
tailscale up
```

Or set `tailscale_auth_key` in the encrypted group variables so the role can
authenticate non-interactively.

### 3. Verify Configuration

```bash
# Check datastore
proxmox-backup-manager datastore list

# Check the local ZFS pool, dataset, and mountpoint
zpool status backup
zfs list backup/pbs
df -h /mnt/datastore

# Check sync jobs (if configured)
proxmox-backup-manager sync-job list

# Check remote configuration
proxmox-backup-manager remote list
```

## Troubleshooting

### ZFS Storage Issues

```bash
# Check pool health and topology
zpool status

# Check the dataset and its effective mountpoint
zfs list -o name,mountpoint
zfs get mountpoint backup/pbs

# Check free space
zpool list
```

### PBS Service Issues

```bash
# Check service status
systemctl status proxmox-backup

# View logs
journalctl -u proxmox-backup -f

# Restart service
systemctl restart proxmox-backup
```

### Ansible Issues

```bash
# Run with verbose output
ansible-playbook site.yml -vvv

# Test connectivity
ansible pbs_servers -m ping

# Check facts
ansible pbs_servers -m setup
```

## Security Best Practices

1. **Always encrypt sensitive files:**

   ```bash
   ansible-vault encrypt group_vars/pbs_servers.yml
   ```

2. **Use strong passwords** for all users

3. **Keep `.vault_pass` secure** and never commit it

4. **Regularly update** PBS and system packages

5. **Use SSH keys** instead of passwords when possible

6. **Review firewall rules** for PBS (port 8007)

## Contributing

When making changes:

1. Test in a development environment first
2. Use `--check` mode before applying
3. Follow the existing role structure
4. Update documentation as needed

## License

This configuration is provided as-is for homelab and personal use.

## Related Projects

- [`../proxmox/`](../proxmox/) - Proxmox VE cluster configuration
