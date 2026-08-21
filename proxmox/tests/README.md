# Test Playbooks

This directory contains local tests that do not connect to Proxmox nodes. The ISO test does make an external HTTPS download; the PBS and IP-Tag tests are self-contained.

## Available Tests

### ISO Management Tests

#### `isos-small.yml`
Tests the `manage_isos` role with an Alpine Linux ISO (about 200 MB). Its checksum is intentionally omitted, so this validates the download path rather than artifact integrity.

```bash
ansible-playbook tests/isos-small.yml
```

**What it tests:**
- ISO directory creation
- ISO download from URL
- File verification

**Output location:** `/tmp/test-isos/`

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

The fixture and command log are written under `/tmp/pbs-backup-job-test/`.

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
rm -rf /tmp/pbs-backup-job-test
```

## Adding New Tests

When adding new test playbooks:

1. Use descriptive names (e.g., `role-name.yml`)
2. Use `localhost` as the target host
3. Set `become: false` to avoid sudo requirements
4. Use `/tmp/` for any test file outputs
5. Document the test in this README
