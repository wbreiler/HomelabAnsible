# Terraform pilot

Start with Proxmox guest lifecycle management. Keep Ansible for host and guest
software configuration. The default configuration only queries node names.
Local pilot settings enable one small, unprivileged Debian container. Existing
production guests remain under their current management.

## Ownership

| Area | Current owner | Intended owner |
|---|---|---|
| Pilot creation, CPU, memory, disk, guest networking | Terraform | Terraform |
| Existing guest provisioning | Ansible or manual configuration | Terraform, one reviewed guest at a time |
| Guest packages, services, application data, updates | Ansible | Ansible |
| PVE host configuration, cluster, storage, backups | Ansible | Ansible |
| TrueNAS, Arista, PBS, workstations | Existing project | Existing project |

`proxmox/tasks/create_lxc.yml` mixes guest creation with guest configuration.
`proxmox/roles/vm_deploy/` also creates guests. Minecraft has a separate
provisioning workflow. Do not give Terraform ownership of a guest until its
Ansible provisioning path stops managing the same settings.

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
`PROXMOX_VE_ENDPOINT` and `PROXMOX_VE_API_TOKEN` shell assignments. Never print
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

## Existing guest migration

For an existing guest, import its current configuration and require a plan
with no changes before any apply. Review disks, mount points, privilege mode,
HA migration behavior, and fields that require replacement. Add
`prevent_destroy` to the guest resource, but do not treat it as a backup or as
protection after removing the resource block.

Keep the first guest unprivileged, without NFS mounts or production data.
Do not begin with existing databases, media services, or Minecraft worlds.

Provider reference: [bpg/proxmox documentation](https://bpg.sh/docs/),
[node data source](https://bpg.sh/docs/data-sources/virtual_environment_nodes/).
