# Local tests

These tests do not connect to Proxmox or download images. Run from `proxmox/`.

## Guest ownership guards

```sh
ansible-playbook -i localhost, tests/terraform-ownership.yml
```

A mutation-rejecting `pct` fixture verifies that absent and stopped guests fail
before software configuration. Only guest discovery/status commands may run.
Expected failures are rescued by the test. Temporary logs are removed.

## Platform ownership guards

```sh
ansible-playbook -i localhost, tests/terraform-platform-ownership.yml
```

Verifies that `pbs_storage`, `pbs_backup_job`, `manage_isos`, and
`download_templates` refuse execution and direct users to Terraform. The old
`pbs-backup-job.yml` and `isos-small.yml` names remain compatibility aliases
for this guard test. They no longer reconcile jobs or download test images.

## Runtime unit tests

```sh
python3 tests/test_iptag.py
python3 tests/test_zipline_client.py
```

These cover IP-tag parsing/filtering and the local upload client respectively.
Terraform mock tests and live adoption checks are documented in
[`terraform/README.md`](../../terraform/README.md).
