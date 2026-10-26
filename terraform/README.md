# Proxmox guest lifecycle

Terraform owns guest provisioning and hardware. Ansible owns host configuration
and guest software. The local deployment now tracks all 32 existing guests:
30 LXCs and two VMs, including the Debian pilot. Adoption imported 31 existing
guests with zero creates, updates, or destroys. A post-import plan had no changes.

Actual guest definitions live in ignored `guests.local.tf` and `vms.local.tf`.
They preserve live disks, network settings, privilege modes, feature flags,
QEMU arguments, and guest identities. Sanitized import examples remain tracked.
The local state and raw configuration snapshots are protected in `artifacts/`.
Deployment files and artifacts contain private infrastructure information and
must not be committed. Keep protected backups of these local files.

Terraform also owns three backup jobs, 27 HA resources, three affinity rules,
the existing PBS storage connection, and 35 cached media files. These 69 objects
were imported without creating, changing, deleting, or downloading anything.
Their definitions live in ignored `platform.local.tf` and `pbs.local.tf`.

## Ownership

| Area | Current owner | Intended owner |
|---|---|---|
| Pilot creation, CPU, memory, disk, guest networking | Terraform | Terraform |
| Existing guest provisioning and hardware | Terraform | Terraform |
| Guest packages, services, application data, updates | Ansible | Ansible |
| Backup jobs, HA policy, PBS connection, cached media | Terraform | Terraform |
| PVE host OS/configuration, cluster bootstrap, recovery operations | Ansible | Ansible |
| TrueNAS, Arista, PBS, workstations | Existing project | Existing project |

The legacy filename `proxmox/tasks/create_lxc.yml` now configures existing
software only. It refuses absent or stopped guests. The `vm_deploy` role and
`proxmox/macos.yml` fail instead of creating VMs. Minecraft's `provision.yml`
imports its existing-server `site.yml`. Boot flag and TUN configuration writes
were removed from application roles. Ansible still configures in-guest NFS
mounts and software. Its old HA workflow now refuses execution. The four former
platform roles are absent from the active Proxmox playbook and reject direct
invocation. Actual PBS host configuration and offsite scripts remain in Ansible.

## First local check

Install Terraform 1.17.0 using the
[official installation instructions](https://developer.hashicorp.com/terraform/install).
This starter was validated with Terraform 1.17.0. Run from `terraform/proxmox/`:

```sh
terraform init -backend=false
terraform fmt -check
terraform validate
terraform test
```

These commands download the pinned provider and validate its schema without
accessing Proxmox. With the cloud configuration present, initialization can
require HCP authentication even with `-backend=false`. Commit
`.terraform.lock.hcl`, including its verified provider checksums. Review
provider upgrades deliberately.

## First live plan

Complete the HCP connection in the State section before running another plan
if `cloud.local.tf` is present.

Use a dedicated read-only API token for discovery. In the Proxmox UI, create
a dedicated user and a privilege-separated API token. Assign `PVEAuditor` at
`/`, with propagation, to both the user and token. Do not reuse an application
token or grant write permissions for this query.

Use an HTTPS endpoint whose certificate your controller trusts. For the PVE
cluster CA, verify its identity through your existing trusted access before
trusting it locally. TLS verification remains enabled.

On macOS, the provider uses Keychain trust. `SSL_CERT_FILE` does not establish
that trust. Retrieve the public cluster CA through an existing trusted SSH
connection and verify its SHA-256 fingerprint. Then add it to the user
Keychain, restricted to SSL for the endpoint address:

```sh
# Replace NODE_ADDRESS with the same hostname or IP used in the API endpoint.
ssh root@NODE_ADDRESS 'cat /etc/pve/pve-root-ca.pem' > /private/tmp/proxmox-ca.pem
openssl x509 -in /private/tmp/proxmox-ca.pem -noout -fingerprint -sha256
security add-trusted-cert -r trustRoot -p ssl -s NODE_ADDRESS \
  -k "$HOME/Library/Keychains/login.keychain-db" /private/tmp/proxmox-ca.pem
```

macOS can request confirmation. This changes certificate trust for the current
user. To remove that trust later, use
`security remove-trusted-cert /private/tmp/proxmox-ca.pem`. See
[Go certificate verification](https://pkg.go.dev/crypto/x509).

Run this in Bash. Enter the full token as `user@realm!token-id=token-secret` at
the hidden prompt. The token does not appear in shell history or process arguments.

```bash
cd terraform/proxmox  # from the repository root
bash
read -r -p 'Proxmox HTTPS endpoint: ' PROXMOX_VE_ENDPOINT
export PROXMOX_VE_ENDPOINT
read -r -s -p 'Proxmox API token: ' PROXMOX_VE_API_TOKEN
printf '\n'
export PROXMOX_VE_API_TOKEN
terraform plan
unset PROXMOX_VE_API_TOKEN
exit
```

The plan should query node names and propose no resource changes. Partial node
visibility can indicate insufficient permissions. The first local plan passed
and returned both cluster nodes. Verify a new plan after connecting HCP.

## State

Use HCP Terraform for state storage and set the workspace execution mode to
**Local** under workspace Settings > General. Terraform must run on the
controller to reach the private Proxmox API. HCP stores the state and provides
locking and state history. Do not put the Proxmox API token into HCP for this
local workflow.

Copy `proxmox/cloud.tf.example` to `proxmox/cloud.local.tf` and enter the HCP
organization and workspace names. The local file is ignored because it holds
deployment-specific configuration. The existing local deployment file already
contains the selected organization and workspace.

From `terraform/proxmox/`, authenticate and initialize:

```sh
terraform login
terraform init
```

`terraform login` opens the browser and prompts for an HCP user API token.
This is a different token from the Proxmox discovery token. Paste it only into
the terminal prompt. Terraform stores HCP credentials outside this repository
in the user's CLI credentials file.

If Terraform detects existing local state, review the destination before
accepting its migration prompt. The initial discovery plan did not create a
local state file. Do not apply if the workspace already contains unexpected
resources or state.

Repeat the live plan with the Proxmox token in the local environment. Confirm
the workspace uses Local execution before supplying that token. An apply can
then save node outputs to HCP without changing guests in discovery-only mode.
The discovery apply and remote state write passed. Verify a new plan after any
resource or credential change.

See [HCP CLI integration](https://developer.hashicorp.com/terraform/cli/cloud).

State, variable files, provider caches, and `*.tfplan` files are ignored. State
and saved plans can contain secrets. Never commit them or publish plan output.
Use the `.tfplan` extension for saved plans. Do not enable Terraform debug logs
with real credentials unless you can protect and remove the resulting logs.

Before managing a persistent guest, verify remote state access, locking, and
state recovery. Git is not a state backup. Do not run concurrent Terraform
operations against local state.

## Disposable Debian pilot

`pilot.tf` declares one container only when `pilot` is non-null. Copy
`pilot.auto.tfvars.example` to `pilot.auto.tfvars`, or use the ignored local
`pilot.auto.tfvars.json` prepared after live discovery. Never allocate its VMID
from an example without checking both live guests and local Minecraft inventory.

The pilot uses one CPU with a one-core quota, 512 MiB RAM, a 4 GiB root disk,
a static address outside the DHCP pool, and an existing SSH public key.
Nesting supports Debian 13 systemd mount namespaces while the container remains
unprivileged. It has no NFS or host mounts, no password,
no application software, and no HA policy. It starts at host boot. The existing
cluster backup job includes new non-Minecraft guests automatically.

`prevent_destroy` blocks Terraform deletion while the resource block remains.
Do not remove the block or disable this guard to clean up the guest without
explicit approval. The existing iptag service owns tags after creation, so
Terraform ignores tag changes. Ansible application roles do not target this
guest. The generic Ansible guest OS update job can still update its packages.

The first DHCP attempt received no offers. The selected static address passed
inventory, reservation, switch ARP, and duplicate-address checks. A control
probe reached the gateway. No switch settings changed. Check address ownership
again before moving or recreating this deployment.

Provider 0.118.0 sends explicit false values for additional feature flags when
setting `nesting`. Proxmox rejects those additional flags for API tokens. The
pilot's nesting setting was bootstrapped with a narrow API request using the
same scoped token, then the guest was rebooted. Terraform declares the final
desired setting and verifies it on refresh. Re-creation with this provider may
need a two-stage bootstrap: create without the `features` block, set only
`nesting=1` through the API, restore the block, and verify a no-change plan.
Do not grant broad host permissions to work around this payload issue.

Use a separate privilege-separated `pilot` API token. Keep the discovery token
read-only. Grant both the owning user and pilot token:

| Path | Role | Purpose |
|---|---|---|
| `/` with propagation | `PVEAuditor` | Read cluster metadata and templates |
| `/vms/SELECTED_ID`, without propagation | `TerraformPilotVM` | Manage only the selected guest |
| `/storage/SELECTED_STORAGE`, without propagation | `PVEDatastoreUser` | Allocate the root disk |
| `/sdn/zones/localnetwork/SELECTED_BRIDGE/SELECTED_VLAN`, without propagation | `PVESDNUser` | Use only the selected guest VLAN |

`TerraformPilotVM` contains `VM.Allocate`, `VM.Audit`, `VM.Config.CPU`,
`VM.Config.Memory`, `VM.Config.Disk`, `VM.Config.Network`, `VM.Config.Options`,
and `VM.PowerMgmt`. Proxmox does not limit storage allocation by VMID or size
through this ACL. The token can allocate storage space on the selected storage.
Keep the token in the ignored `.env` file with mode `0600`. It contains only
`PROXMOX_VE_ENDPOINT`, `PROXMOX_VE_API_TOKEN`, and `TF_VAR_pbs_storage_password`
shell assignments. Never print
or commit its contents. This token has no scheduled expiration. Revoke it when
the pilot is retired, or replace it deliberately.

From `terraform/proxmox/`, use a subshell to keep credentials out of the parent
shell environment. The Terraform executable must be on `PATH`:

```sh
(
  set -eu
  set -a
  . ./.env
  set +a
  terraform plan -out=pilot.tfplan
)
```

Review the plan. Apply only the saved plan that creates the expected pilot,
with no changes to existing resources:

```sh
(
  set -eu
  set -a
  . ./.env
  set +a
  terraform apply pilot.tfplan
)
```

Verify the guest boots, has the selected guest-network address, and accepts the
configured SSH key. Repeat `terraform plan -detailed-exitcode` and require
exit code `0` before declaring convergence. Mock-provider tests verify the
discovery-only default and the pilot's resource limits without accessing PVE.

The first deployment passed direct SSH authentication, systemd boot health,
DNS resolution, gateway reachability, and a final no-change plan. Both mock
tests and the repository's Proxmox Ansible lint check passed. Disaster recovery
and guest restoration remain untested.

## Existing guest adoption

`artifacts/imports-2026-10-26.local.tf` records the completed imports, original
node/IDs, and stable Terraform addresses. Completed blocks are archived outside
the active module so mock-provider tests do not attempt imports. The pilot keeps
its original address. Each imported guest has `prevent_destroy = true`. Removing the entire
resource block removes that guard, so never use file deletion as cleanup.

The infrastructure token currently retains its original `pilot` name. It uses
the `TerraformGuest` role only on the adopted guest IDs and `PVEDatastoreUser`
on their storage pools. The discovery token remains read-only. `TerraformGuest`
contains the pilot VM permissions plus `VM.Config.HWType`, `VM.Config.CDROM`,
and `VM.Config.Cloudinit`. The network permission remains scoped to the guest
VLAN. Creating a guest with a new ID requires an ACL grant for that ID first.

Several import corrections were necessary with provider 0.118.0:

- Unset CPU units imported as zero, which the provider rejects in configuration.
  Leave those optional/computed units unset instead of changing CPU scheduling.
- LXC imports contain a zero start timeout. Ignore that provider-local timeout
  metadata to avoid an otherwise unnecessary update during adoption.
- macOS presents ISO boot files as disks. Leave invalid imported `iso` format
  and zero-size fields unset so computed state preserves the actual media.
- Preserve explicit disk controller settings. The macOS VM's controller is
  implicit, so its `scsi_hardware` remains ignored rather than applying the
  provider's different default.
- Ignore tags maintained by iptag. For HA guests, also ignore node and started
  state so Terraform does not fight HA placement or power decisions.

Raw `lxc.*` entries, including existing bind mounts and TUN passthrough, remain
in Proxmox and the protected raw snapshots. The provider does not represent
every such entry. Import does not convert these entries into Terraform-managed
attributes, and it does not recreate application data. Existing images,
templates, boot media, backups, and hardware-specific setup remain prerequisites
for recovery. Preserve privilege modes on the existing NFS guests.

For another adoption, start with `imports.local.tf.example`. Generate a fresh
local definition file, add deletion guards, and inspect the saved plan JSON.
Require every imported resource's action to be `no-op` before applying the
import plan. A plan that imports and also updates a guest is not acceptable.
Back up state first, then require a no-change plan and compare live guest
configuration, placement, and power state against the pre-import snapshot.

For a new guest, define a resource with a reviewed OS image or template, public
SSH key, privilege mode, storage, address, and backup coverage. The example
imports describe adoption, not a blank-system restore procedure.

Ansible ownership tests reject absent and stopped guests before software work.
No application playbooks were applied to production during this migration.
Disaster recovery, guest restoration, and resizing production guests remain
untested. Read the generated definitions and the provider-specific limitations
before authorizing a production hardware change.

## Platform policy and media

The imported backup jobs preserve schedules, selected/excluded VMIDs, enabled
state, retention, and notifications. HA definitions preserve desired state,
node priorities, strictness, failback, and rebalancing. The HA service still
controls runtime guest placement and power. Rule order is preserved in Proxmox;
the provider does not model that native field.

The PBS connection keeps its existing namespace, certificate fingerprint,
credential, storage visibility, and encryption setup. The existing password was
read through trusted SSH into the owner-only ignored environment file. It is
supplied as a sensitive variable. Password and encryption-key fields are ignored
for the existing resource because the API does not return their current values.
Do not remove these ignores or enable key generation to reconcile an import.
Credential rotation needs an explicit reviewed change. The provider did not
read the existing storage-level prune defaults, so those remain preserved in
the native storage configuration. Backup-job retention is represented explicitly.

Existing media uses `proxmox_virtual_environment_file`, with deletion guards
and creation-only metadata ignored. Eleven LXC templates have pinned HTTPS
sources and SHA256 checksums. Available official catalog SHA512 values matched
the cached bytes. Older Debian 13 templates were not in the current catalog,
so their pins describe observed trusted-host bytes, not fresh upstream verification.
Versioned archive URLs can expire and must be checked before reconstruction.

The other 24 files are existing ISOs and custom boot media whose original
download sources are not recorded. They are protected and tracked without
inventing source URLs. Restore these files from protected media backups or
supply a verified source before recreating them. No image bytes were downloaded
or replaced during adoption. The template upload resource can fetch a pinned
source through the controller if a future create is authorized. See
`image.tf.example` for a new versioned image. Never overwrite a guest's active
boot media to update a version.

The direct download resource proposed cached-file replacements during import
because of its imported metadata. Its deletion guards stopped that plan, and
it was not applied. The file resource then produced a 69-object import-only
plan. Completed imports and protected before/after snapshots are archived
under `artifacts/`.

Permissions for the infrastructure token now also include:

| Scope | Role | Purpose |
|---|---|---|
| `/`, without propagation | `TerraformClusterPolicy` | `Sys.Audit`, `Sys.Modify`, and `Sys.Console` required by backup and HA APIs |
| `/storage/mnemosyne`, without propagation | `TerraformBackupConnection` | `Datastore.Audit` and `Datastore.Allocate` for the existing PBS connection |
| `/storage/local`, without propagation | `TerraformImageStorage` | `Datastore.Audit` and `Datastore.AllocateTemplate` for cached media |

Proxmox checks cluster policy rights at `/`; it cannot restrict these privileges
to individual backup-job or HA-rule IDs. The new root grant does not propagate
to node paths, but it still permits other operations checked at the root path.
Do not describe it as job-only access.

Local guard tests, Terraform mock plans, and post-import no-change plans verify
the ownership boundary. Live backup/HA/storage settings and file metadata are
compared with the pre-import snapshot. Actual restore, failover, credential
rotation, and media reconstruction are separate tests and remain unverified.

Provider reference: [bpg/proxmox documentation](https://bpg.sh/docs/),
[node data source](https://bpg.sh/docs/data-sources/virtual_environment_nodes/).
