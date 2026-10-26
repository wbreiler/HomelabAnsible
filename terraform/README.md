# Terraform pilot

Start with Proxmox guest lifecycle management. Keep Ansible for host and guest
software configuration. This first stage only queries node names. It declares
no managed resources and does not transfer ownership of any existing guest.

## Ownership

| Area | Current owner | Intended owner |
|---|---|---|
| Guest creation, CPU, memory, disks, guest networking | Ansible or manual configuration | Terraform, one reviewed guest at a time |
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
```

These commands download the pinned provider and validate its schema without
accessing Proxmox. With the cloud configuration present, initialization can
require HCP authentication even with `-backend=false`. Commit
`.terraform.lock.hcl`, including its verified provider checksums. Review
provider upgrades deliberately.

## First live plan

Complete the HCP connection in the State section before running another plan
if `cloud.local.tf` is present.

Use a dedicated read-only API identity for this stage. In the Proxmox UI, create
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
then save node outputs to HCP without changing guests. Authentication, workspace
execution mode, initialization, and remote state writes require live checks.

See [HCP CLI integration](https://developer.hashicorp.com/terraform/cli/cloud).

State, variable files, provider caches, and `*.tfplan` files are ignored. State
and saved plans can contain secrets. Never commit them or publish plan output.
Use the `.tfplan` extension for saved plans. Do not enable Terraform debug logs
with real credentials unless you can protect and remove the resulting logs.

Before managing a persistent guest, verify remote state access, locking, and
state recovery. Git is not a state backup. Do not run concurrent Terraform
operations against local state.

## Next stage

1. Verify the read-only live plan.
2. Select a disposable guest and confirm its VMID against live and local inventory.
3. Configure the state backend before adding a managed resource.
4. Give Terraform sole ownership of that guest's provisioning settings.
5. Review the plan before any apply.

For an existing guest, import its current configuration and require a plan
with no changes before any apply. Review disks, mount points, privilege mode,
HA migration behavior, and fields that require replacement. Add
`prevent_destroy` to the guest resource, but do not treat it as a backup or as
protection after removing the resource block.

Keep the first guest unprivileged, without NFS mounts or production data.
Do not begin with existing databases, media services, or Minecraft worlds.

Provider reference: [bpg/proxmox documentation](https://bpg.sh/docs/),
[node data source](https://bpg.sh/docs/data-sources/virtual_environment_nodes/).
