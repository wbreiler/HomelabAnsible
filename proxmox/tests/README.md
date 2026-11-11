# Local tests

The tests below run locally without Proxmox connections or image downloads.
Run them from `proxmox/`. Guest integration tests have separate requirements
at the end of this guide.

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
python3 tests/test_lxc_auto_update.py
python3 tests/test_lxc_app_updates.py
python3 tests/test_native_app_updates.py
python3 tests/test_lxc_update_notifications.py
python3 tests/test_local_dns.py
python3 tests/test_homebridge_mdns_proxy.py
python3 tests/test_netdata.py
```

These cover IP-tag parsing/filtering, the local upload client, and application
filesystem/credential boundaries. The boundary fixtures use PyYAML from the
Ansible environment and run without application code, downloads, or live hosts.
The logging fixtures also use Jinja2 to check the explicit source policy,
listener addresses, permitted ingress routes, and isolated retention ports.
Application updater tests cover stable release selection, package aging,
artifact integrity, backup gates, failed-retry blocking, saved pins, and
native archive/release preservation. Run them with Ansible's Python environment.
Notification tests cover stale reports, failure summaries, credential redaction,
Discord message limits, disabled mentions, delivery confirmation, and rate limits.
Netdata tests use Jinja2 to check network restrictions, private stream credentials,
and preservation of unrelated Open WebUI providers and tools. See the
[Netdata guide](../docs/netdata.md) for live chat acceptance.
DNS tests verify additive records and conflict rejection. Homebridge tests
validate public advertisement data without contacting Avahi or a gateway.
Terraform mock tests and live adoption checks are documented in
[`terraform/README.md`](../../terraform/README.md).

## Tests that need a guest

`tests/test_nexdeck_homelab.py` imports the installed NexDeck backend. Run it
with the guest's venv as described in the [NexDeck guide](../files/nexdeck/README.md).
It is not part of a dependency-free local discovery run.

`tests/verify_local_services_ingress.py` requires root in the proxy guest for
an isolated network namespace. See the [private services guide](../docs/local-services.md).
The Gatus, Apt-Cacher NG, and LibreSpeed guest playbooks also require explicitly
selected disposable guests. Static checks do not substitute for these live tests.
