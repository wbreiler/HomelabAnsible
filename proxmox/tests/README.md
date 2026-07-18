# Test Playbooks

This directory contains test playbooks for validating roles without requiring access to actual Proxmox nodes.

## Available Tests

### ISO Management Tests

#### `isos-small.yml`
Tests the `manage_isos` role with a small Alpine Linux ISO (~60MB).

```bash
ansible-playbook tests/isos-small.yml
```

**What it tests:**
- ISO directory creation
- ISO download from URL
- File verification

**Output location:** `/tmp/test-isos/`

#### `isos.yml`
Tests the `manage_isos` role with a full Ubuntu Server ISO (~2GB).

```bash
ansible-playbook tests/isos.yml
```

**Note:** This downloads a large file. Use `isos-small.yml` for quick validation.

### PBS Backup Job Tests

#### `pbs-backup-job.yml`

Tests backup-job reconciliation locally with a fake `pvesh` command.

```bash
ansible-playbook tests/pbs-backup-job.yml
```

**What it tests:**

- Schedule, mode, compression, and VMID updates
- Restricted-to-all and all-to-restricted guest transitions
- No update for an already converged job

### IP-Tag Runtime Tests

#### `test_iptag.py`

Tests the repository-owned IP-Tag configuration parser, guest-list parsing, address extraction, filtering, and tag formatting.

```bash
python3 tests/test_iptag.py
```

## Cleanup

After running tests, clean up downloaded files:

```bash
rm -rf /tmp/test-isos
```

## Adding New Tests

When adding new test playbooks:
1. Use descriptive names (e.g., `role-name.yml`)
2. Use `localhost` as the target host
3. Set `become: false` to avoid sudo requirements
4. Use `/tmp/` for any test file outputs
5. Document the test in this README
