# Proxmox Backup Server Ansible Configuration

Automated deployment and configuration of Proxmox Backup Server with NFS storage, user management, and Tailscale integration using a modular role-based structure.

## Features

- ✅ Installs Proxmox Backup Server from no-subscription repository
- ✅ Disables enterprise repository
- ✅ Mounts NFS share with optimized settings
- ✅ Creates and manages PBS users with secure passwords
- ✅ Configures MainStore datastore on NFS
- ✅ Optional remote configuration for sync/pull jobs
- ✅ Installs and configures Tailscale VPN

## Prerequisites

- Debian-based system (tested on Debian 12 Bookworm)
- ansible-core 2.16 through 2.21 installed on the control node
- Root or sudo access on target PBS server
- NFS server configured and accessible
- Python 3 on target hosts

## Quick Start

### 1. Clone and Configure

```bash
# Clone or create the repository
cd pbs-ansible

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
# Create vault password file (add to .gitignore)
echo "your-vault-password" > .vault_pass
chmod 600 .vault_pass

# Encrypt the group vars file
ansible-vault encrypt group_vars/pbs_servers.yml
```

### 3. Run the Playbook

```bash
# Run all roles
ansible-playbook site.yml --vault-password-file .vault_pass

# Run with tags (specific roles only)
ansible-playbook site.yml --vault-password-file .vault_pass --tags pbs,users

# Skip specific roles
ansible-playbook site.yml --vault-password-file .vault_pass --skip-tags tailscale

# Dry run (check mode)
ansible-playbook site.yml --vault-password-file .vault_pass --check
```

## Directory Structure

```
pbs-ansible/
├── ansible.cfg                           # Ansible configuration
├── site.yml                              # Main playbook
├── inventory.yml                         # Server inventory (DO NOT COMMIT)
├── inventory.yml.example                 # Example inventory
├── .gitignore                            # Git ignore rules
├── .vault_pass                           # Vault password (DO NOT COMMIT)
├── group_vars/
│   ├── pbs_servers.yml                  # Variables for PBS servers (DO NOT COMMIT)
│   └── pbs_servers.yml.example          # Example variables
├── roles/
│   ├── nfs_mount/                       # NFS mounting role
│   │   ├── tasks/main.yml
│   │   └── defaults/main.yml
│   ├── users/                           # User management role
│   │   ├── tasks/main.yml
│   │   └── defaults/main.yml
│   ├── pbs/                             # PBS installation and config role
│   │   ├── tasks/main.yml
│   │   ├── defaults/main.yml
│   │   └── handlers/main.yml
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

# NFS Configuration
nfs_mount_server: "192.168.4.211"
nfs_mount_export_path: "/volume1/PBS"
nfs_mount_opts: "rw,relatime,vers=3,rsize=131072,wsize=131072,hard,proto=tcp,noatime"

# Pull Job (runs weekly on Saturday at 11:30 PM)
pbs_configure_pull_job: true
pbs_pull_schedule: "sat 23:30"
```

## Roles

### nfs_mount

Mounts NFS shares for PBS storage with performance-optimized settings.

**Tags:** `nfs`, `storage`, `setup`

**Variables:**

- `nfs_mount_path`: Mount point (default: `/mnt/pbs-nfs`)
- `nfs_mount_server`: NFS server address
- `nfs_mount_export_path`: NFS export path
- `nfs_mount_opts`: Mount options (optimized for performance)

### users

Creates and manages PBS users with secure password hashing.

**Tags:** `users`, `setup`

**Variables:**

- `users_pbs_users`: List of users to create (default: empty; placeholder passwords are rejected)
- `users_root_password`: Root user password

### pbs

Installs Proxmox Backup Server, configures datastore, and manages remote sync/pull jobs.

**Tags:** `pbs`, `setup`

**Variables:**

- `pbs_datastore_name`: Datastore name (default: `MainStore`)
- `pbs_datastore_path`: Datastore path
- `pbs_configure_remote_sync`: Enable remote sync (push)
- `pbs_configure_pull_job`: Enable pull job
- `pbs_pull_schedule`: Pull schedule (e.g., `"sat 23:30"`)

### tailscale

Installs and configures Tailscale VPN (optional).

**Tags:** `tailscale`

**Variables:**

- `install_tailscale`: Enable Tailscale (default: `true`)
- `tailscale_authenticate`: Auto-authenticate
- `tailscale_args`: Additional arguments for `tailscale up`

## Usage Examples

### Run Specific Roles

```bash
# Only configure NFS and PBS
ansible-playbook site.yml --tags nfs,pbs

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

# Run playbook with vault (password file configured in ansible.cfg)
ansible-playbook site.yml
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

Or set `tailscale_authenticate: true` and provide an auth key in `tailscale_args`.

### 3. Verify Configuration

```bash
# Check datastore
proxmox-backup-manager datastore list

# Check NFS mount
df -h /mnt/pbs-nfs

# Check pull jobs (if configured)
proxmox-backup-manager pull-job list

# Check remote configuration
proxmox-backup-manager remote list
```

## Troubleshooting

### NFS Mount Issues

```bash
# Check NFS server exports
showmount -e 192.168.4.211

# Test manual mount
mount -t nfs 192.168.4.211:/volume1/PBS /mnt/test

# Check NFS client packages
dpkg -l | grep nfs-common
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

- [proxmox-ansible](https://git.wbreiler.com/wbreiler/proxmox-ansible) - Proxmox VE cluster configuration
