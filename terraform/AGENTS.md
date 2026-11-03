# AGENTS.md

Guidance for `terraform/` and its Proxmox module. Follow the repository's
[root guidance](../AGENTS.md) and [deployment guide](README.md).
Run Terraform and module tests from `terraform/proxmox/`.

## Ownership and state

Terraform owns guest creation, hardware, boot declarations, backup jobs, HA
policy, the PVE-to-PBS connection, and cached media. Ansible configures hosts
and existing guest software. Do not move these resource owners into Ansible.
HA retains runtime placement/power decisions. The IP-tag service retains tags.

`proxmox/main.tf` pins Terraform and the Proxmox provider and enables TLS
verification. Preserve the provider lockfile. Review version and checksum
changes together. On macOS, follow the README's verified Keychain procedure
instead of disabling TLS verification.

HCP stores state, locking, and history. Its execution mode must remain **Local**
so the controller can reach the private API. Use the configured SSH agent and
public key selectors. Keep API credentials in the protected local environment.
The discovery token and the scoped infrastructure token have different purposes.

Real guests, platform policy, and the cloud backend live in ignored
`*.local.tf` files. Profiles, `.env`, variable files, plans, state snapshots,
logs, and artifacts are private. Never print them wholesale or commit them.
Save plans with the ignored `.tfplan` extension. Git is not a state backup.

## Code map

| Path under `proxmox/` | Purpose |
| --- | --- |
| `main.tf`, `platform.tf`, `pilot.tf` | Provider/discovery, sensitive PBS input, and bounded pilot definitions |
| `iso.tf`, `pxe.tf`, `debian-install.tf`, `iso-install.tf` | Pinned media and installation resources |
| `scripts/deploy_guest.py` | Validated profile, VMID allocation, guarded plans, and application handoff |
| `scripts/pxe_install.py`, `scripts/iso_install.py` | PXE publication, retained ISO construction, and installed-guest verification |
| `*.tftest.hcl`, `tests/` | Mock-provider and local Python regression checks |

## Guest workflow

`scripts/deploy_guest.py PROFILE` applies infrastructure and runs Ansible.
It is not a diagnostic command. Use it only within an authorized deployment.
For a preview, use `python3 scripts/deploy_guest.py PROFILE --plan-only`.
The preview still reads live state and creates protected local artifacts.
It restores temporary definition edits and does not apply or run Ansible.

- Supported applications are Gatus, Apt-Cacher NG, and LibreSpeed. The workflow
  supports Debian LXCs and Debian/Ubuntu PXE VMs with UEFI and Secure Boot.
  The PXE service must exist before library publication or guest deployment.
  Preserve legacy ISO inputs and caches. PXE does not authorize their deletion.
  Ubuntu PXE needs at least 8 GiB RAM. Retire automatic entries only after
  installed-system verification. Re-arm them only for a reviewed new VM creation.
  The lower-level ISO installer also supports Fedora. Do not conflate them.
- VMID allocation checks the live cluster, ignored Minecraft definitions,
  and retained installation inputs. Preserve their reservations. Check IP
  allocation separately because a failed SSH probe does not prove an address is free.
- Preserve profile validation, the plan allowlist, global/per-guest locks,
  and the scoped ACL grant. The LXC bootstrap permits only the verified
  stopped guest's nesting setup followed by a power-only start plan.
- A repeat run can resume application configuration. It must reject hardware
  changes, replacements, deletion, missing managed guests, or unrelated guests.
  Preserve failed-run definitions and evidence. Do not destroy a failed guest automatically.
- Application variables belong in a protected `app_vars_file`. Keep the
  application prefix allowlist and reject transport overrides. New applications
  require a guest-targeted Ansible entry point, tests, and documentation.

## Adoption and recovery safeguards

Read the [adoption notes](README.md#existing-guest-adoption) before importing
resources. Preserve imported disk settings, MAC identities, privilege modes,
HA ignores, tags, and raw LXC passthrough snapshots. The provider does not
represent every native field. Import alone does not prove disaster recovery.

Back up state and native configuration before adoption. Require import-only
plans with `no-op` resource actions. Apply only the reviewed saved plan, then
require a no-change plan and compare the resulting native configuration.

Preserve `prevent_destroy`. Removing a resource block removes that protection.
Do not remove definitions as routine cleanup. Guest/disk deletion requires
explicit authorization for those targets and a reviewed removal plan.
Preserve original ISO files, recovery media, credentials, and backup contents.
The historical resource counts and VM 108 records are not current inventory.

## Validation

Use the pinned tools and existing provider installation. From `proxmox/`:

```sh
terraform fmt -check
terraform validate
terraform test
python3 -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

Python installer tests require `xorriso` and use generated fixtures. Terraform
tests use mock providers. Initialization can download providers or require HCP
authentication, even with `-backend=false`. Do not describe it as offline.
Keep completed imports outside the active module, as the README specifies.

For changes to the application handoff, also validate the affected Proxmox
Ansible entry point from `../../proxmox/`. After an authorized live run,
verify guest identity, application health, and Terraform convergence separately.
