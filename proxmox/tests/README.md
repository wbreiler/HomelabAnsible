# Local tests

These tests do not connect to Proxmox or download images. Run from `proxmox/`.

## Guest ownership guards

```sh
ansible-playbook -i localhost, tests/terraform-ownership.yml
ansible-playbook -i localhost, tests/check-mode.yml
```

A mutation-rejecting `pct` fixture verifies that absent and stopped guests fail
before software configuration. Only guest discovery/status commands may run.
Expected failures are rescued by the test. Temporary logs are removed.
The check-mode fixture also verifies that a running guest permits discovery,
status, and readiness checks without any configuration command.

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
python3 tests/test_service_boundaries.py
python3 tests/test_logging_ingress.py
```

These cover IP-tag parsing/filtering, the local upload client, and application
filesystem/credential boundaries. The boundary fixtures use PyYAML from the
Ansible environment and run without application code, downloads, or live hosts.
The logging fixtures also use Jinja2 to check the explicit source policy,
listener addresses, permitted ingress routes, and isolated retention ports.
Terraform mock tests and live adoption checks are documented in
[`terraform/README.md`](../../terraform/README.md).
