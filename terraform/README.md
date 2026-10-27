# Proxmox guest lifecycle

Terraform owns guest provisioning and hardware. Ansible owns host configuration
and guest software. The local deployment now tracks 32 guests:
30 LXCs and two VMs, including the Debian pilot. The disposable ISO test passed
and its VM was subsequently removed through Terraform.
Adoption imported 31 existing
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
The separate ISO library now adds ten installers on each node, for 20 new
cached files. Disposable boot-test cleanup left 121 managed resources. The
Gatus test guests were also removed through Terraform. Their installation
identity, build record, and private ISO increase the total to 124 resources.
The workflow validation pair was also removed through Terraform, returning
to 124 managed resources without removing any media.
All destination SHA256 hashes
matched the trusted NAS files, and the final Terraform plan had no changes.

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

## Create a guest and install its application

Run one command from `terraform/proxmox/` after preparing a private profile:

```sh
python3 scripts/deploy_guest.py status-lxc.profile.json
```

Copy `guest-lxc.profile.json.example` or `guest-vm.profile.json.example` to a
local `*.profile.json` file. These local profiles are ignored by Git. Set the
name, node, unused static IP and gateway, VLAN, DNS, and existing template or
pinned source ISO. The examples contain documentation addresses only.
The workflow reads credentials from the protected local `.env`, uses `TF_BIN`
or Terraform on `PATH`, and uses the configured SSH agent with public-key
selectors. No secret is passed as a command argument.

The first supported application is **Gatus**, using the existing pinned role.
LXCs use Debian templates. VMs support Debian or Ubuntu installation ISOs and
always use UEFI with Secure Boot. Unsupported apps and Fedora profiles fail
before provisioning because the current guest application role requires a
Debian-family guest. Other applications need a guest-targeted Ansible entry
point before they can join the allowlist. Legacy node-targeted roles are not
called by this workflow.

The command performs these steps without interactive Terraform approval:

1. Validate the profile and select the first unused VMID, unless one is supplied.
2. Review a saved plan that allows only the new guest and its installation resources.
3. Grant the existing Terraform role on that unused VMID and apply the saved plan.
4. Wait for SSH, verify the guest hostname, and configure the app through Ansible.
5. Require a converged Terraform plan and verify application health through the role.

VMID allocation checks live guests, retained installer inputs, and the ignored
Minecraft deployment. Retained installer inputs also reserve their original
VMIDs and IPs in the existing installer schema.
IP checks reject addresses already present in Terraform state or accepting SSH.
Use an allocated static IP outside DHCP. These checks cannot prove that every
unmanaged or powered-off network device has released an address.
The scoped `TerraformGuest` role must already exist. Trusted root SSH to the
Proxmox endpoint grants that existing role only on the new `/vms/<id>` path,
for the configured API user and token. It does not change existing guest,
cluster, network, or storage permissions.

New LXCs default to two cores, 2 GiB RAM, and an 8 GiB disk. VMs default to two
cores, 2 GiB RAM, and a 24 GiB disk. Both default to host auto-start enabled.
VM system disks default to backup enabled. Disposable validation profiles
explicitly disable both. LXCs follow the existing backup
selection. Profiles can set `cores`, `memory_mb`, `disk_gb`, `on_boot`, and VM
`backup`. LXCs remain unprivileged, without host or NFS mounts.

Provider 0.118.0 requires a narrow nesting bootstrap for Debian LXCs. The first
saved plan creates only the new, stopped container. A Terraform creation
provisioner verifies its VMID, hostname, privilege mode, and stopped state,
then sets only `nesting=1` through trusted root SSH. The canonical definition
then declares nesting, and a second guarded plan may only start that container.
Before controller SSH, a gateway probe from the new LXC refreshes stale ARP
entries when an address is reused. Application Ansible never writes guest
lifecycle or hardware settings.

Use `--plan-only` to validate the creation plan without changing infrastructure
or running Ansible. Temporary deployment edits are restored afterward. The LXC
preview covers its initial stopped creation and nesting provisioner. It does
not apply the subsequent power-only plan. A global lock serializes Terraform
work, while a per-guest lock prevents concurrent configuration of one guest.

Repeat the same command to resume an application failure or rerun configuration.
Completed guests retain deletion guards. The workflow refuses guest hardware
updates, replacements, deletions, missing managed guests, and existing guests
without its own deployment record. An installation failure preserves the
configuration and state for review. It never automatically destroys a guest.
A reviewed new VM creation can reuse an unchanged retained installation entry.
The previous SSH verification record is archived. The installer verifies the
installation UUID and OS before accepting the new guest host key.

Generated definitions, private profiles, one-host inventories, host keys,
plans, state snapshots, logs, and the success record remain under ignored
local files and `artifacts/deploy/<name>/`. Keep these files protected and
backed up. The VM input map preserves all other installation entries.
Optional `app_vars_file` names a protected JSON file containing only `gatus_*`
settings, excluding `gatus_guest_ssh`. This supports application configuration
without exposing secret values in process arguments. Paths are resolved from
the command's working directory.

Live validation on 2026-10-26 created `workflow-lxc-test` (LXC 132) and
recreated the removed `gatus-vm-test` (VM 133) using its unchanged retained ISO.
Both installed Gatus, passed dashboard and local-monitoring health checks,
and passed repeat workflow and Ansible dry-runs with zero changes. The VM
verified UEFI, Secure Boot, enrolled keys, kernel lockdown, and system health.
The 32 baseline guests and all 56 media files remain unchanged.

After explicit approval, a reviewed Terraform plan removed both validation
guests, their disks, and their readiness record. All 32 baseline guests and
56 media files remain unchanged. The reusable workflow, Ansible support,
private profiles, installation media, and archived guest definition remain
available. The final plan has no changes, and deletion guards are restored.
Evidence and the applied plan remain under
`artifacts/workflow-validation-2026-10-26/`.
The installed Terraform binary is cached under ignored `terraform/.tools/`,
and the local `.env` selects it through `TF_BIN`.

Validation:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Gatus application test pair

The application test used one unprivileged Debian LXC and one Debian VM
with UEFI and Secure Boot enabled. Both guests were removed through a reviewed
Terraform plan after validation. All other guests and every ISO remain unchanged,
including the private Debian installation image. Its Terraform identity, build
record, and media resource remain managed and protected from deletion.

Reusable machine-specific definitions remain in ignored `app-tests.local.tf` and
`iso-install.auto.tfvars.json`. The protected Ansible inventory is
`artifacts/app-tests.inventory.yml`, with snapshots and evidence alongside it.
Never commit these deployment files. The shared app role, playbook, and
sanitized inventory example remain tracked under `proxmox/`.

The ignored `app-tests-cleanup_override.tf` disables the removed test guests and
their readiness record while retaining their media. Deletion guards are enabled.
Do not remove this override without reviewing live VMIDs, IP addresses, and a
new creation plan. Refresh the private Ansible inventory before reusing it.
The preserved LXC definition uses nesting for Debian 13 systemd mounts, with
the narrow provider bootstrap workaround described below. Ansible does not
manage this feature or perform guest restarts.

Run Ansible from `proxmox/` with its project configuration:

```sh
ansible-playbook -i ../terraform/proxmox/artifacts/app-tests.inventory.yml gatus-guests.yml --check --diff
ansible-playbook -i ../terraform/proxmox/artifacts/app-tests.inventory.yml gatus-guests.yml
```

Gatus 5.36.0 passed dashboard, local-health, and peer-health checks on both
guests. A repeat Ansible run made zero changes. Both services survived a
Terraform-managed restart, and the VM reverified Secure Boot and kernel
lockdown afterward. The original 32 guests and 55 original cached media files
remained unchanged during the installation test. Protected validation results
are in `artifacts/app-tests-validation-summary-2026-10-26.json`. The cleanup
audit is in `artifacts/app-tests-cleanup-summary-2026-10-26.json`.

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
- Leave the VM's top-level `mac_addresses` reporting field unset. Preserve
  configured MAC addresses inside `network_device` instead, so runtime reporting
  cannot propose a hardware update for a stopped guest.
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

### ISO library

`proxmox/iso.tf` caches a checksum-pinned ISO library on each selected node.
Copy `iso.auto.tfvars.example` to ignored `iso.auto.tfvars` and supply the
server URL, nodes, and filename-to-SHA256 map. Obtain hashes through trusted
access to the source files. A hash pins those bytes but does not establish
the publisher's identity. Use a new filename for each new image version.

The deployment uses the dedicated Erebus ISO server. Its actual address,
node selection, and observed source hashes remain in ignored local variables.
Existing adopted media keeps its original Terraform addresses and filenames.
Even similar names or equal sizes do not establish identical content.

Each new ISO has `overwrite = false`, `overwrite_unmanaged = false`, and
`prevent_destroy = true`. Source URLs and checksums are creation metadata,
ignored after creation or adoption. This permits adoption without replacing
cached bytes when the API does not return their original source metadata.
A new source or checksum must use a new filename and resource key. A filename
replacement is rejected by the deletion guard.
Do not remove guards or existing resource blocks to update installation media.
These resources prepare installers. They do not attach media, change boot
order, boot an installer, or install an operating system inside a VM.

The nodes download directly from the ISO server using `proxmox_download_file`.
The existing token already has the required storage permission and root-scope
`Sys.Audit`/`Sys.Modify` privileges used by platform policy. No additional grants
are needed. Use `terraform apply -parallelism=2 reviewed.tfplan` to limit
simultaneous transfers. See the pinned provider's
[download resource documentation](https://github.com/bpg/terraform-provider-proxmox/blob/v0.118.0/docs/resources/download_file.md).

Before applying, require a saved plan that only adds expected ISO resources.
Check node storage capacity and preserve a protected state snapshot. Afterward,
compare destination SHA256 hashes with the trusted source pins, require a
no-change plan, and verify existing guest configurations and media metadata.

The initial live deployment passed all 20 destination checksum comparisons,
preserved existing media sizes/timestamps, and completed with a no-change plan.
Active guest configuration matched the protected adoption snapshot, excluding
API digests and temporary lock/snapshot-parent metadata from scheduled backups.
Six mock-provider tests, Terraform validation/formatting, and Proxmox Ansible
lint/syntax checks passed. One completed upload was adopted without replacing
its bytes when transfers switched to direct node downloads. Completed import
blocks and protected before/after state snapshots remain in ignored `artifacts/`.
Automatic installation validation is covered below.

### Automatic Debian, Ubuntu, and Fedora installation

`proxmox/iso-install.tf` provisions fresh AMD64 server VMs in one Terraform
apply. It builds a separate private ISO, creates the VM, and waits until SSH
confirms the installed OS, generated machine UUID, completion marker, disk
root, locked accounts, disabled password/root SSH login, guest-agent health,
and zero failed systemd units. It never types installer answers into a console.

Supported source profiles are Debian netinst, Ubuntu live-server, and Fedora
Server DVD. Select a filename already present in the checksum-pinned
`iso_library`. The source is cached and SHA256-verified on the controller.
Original NAS and Proxmox ISOs are never edited or replaced.

The controller needs Python 3.11+, xorriso, and an unlocked SSH agent containing
the private counterpart of the selected public key. On this Mac, xorriso
1.5.8.pl02 was installed with Homebrew. No build tools were installed on PVE.
The HCP workspace must retain Local execution mode.

1. Copy `iso-install.auto.tfvars.example` to ignored `iso-install.auto.tfvars`.
2. Select an unused sequential VMID, checked address, source ISO, node, and VM storage.
3. Grant the existing Terraform identity its existing guest role only on the new VMID.
4. Review and apply a saved plan containing only the requested new resources:

   ```sh
   terraform plan -out=install.tfplan
   terraform apply -parallelism=2 install.tfplan
   terraform output installed_vms
   ```

5. Connect to the declared address with the selected SSH key.

Terraform generates and retains the machine UUID automatically. Default bounds
are two CPU cores with a matching limit, 2 GiB memory, and one 24 GiB SCSI disk.
Normal VMs enable host boot and backup of the system disk. Validation VMs
explicitly disable both. The existing cluster backup policy determines coverage.
No HA or replication policy is added automatically.

Set `firmware = "uefi"` before creation to use OVMF, a q35 machine, and a
private persistent 4m EFI variables disk on the selected VM datastore. BIOS
remains the default and has no EFI disk. Set `secure_boot = true` together
with UEFI to populate the EFI disk with Proxmox's standard enrolled keys and
enable Secure Boot. The default remains `false` for existing configurations.
Firmware or Secure Boot policy changes require replacement, which the deletion
guard blocks. Create a new VM entry for a different policy. No custom signing
keys, MOK enrollment, or TPM provisioning are needed for these signed distro
bootloaders and kernels. TPM and custom module signing remain outside this workflow.

Debian receives a root-only preseed inside its initramfs. Ubuntu receives
`autoinstall.yaml` on the derived media. Fedora receives Kickstart on that
media. Each installer verifies its own machine UUID before partitioning and
selects only `/dev/sda`. The boot menus default immediately to installation.
Xorriso retains the hybrid BIOS/UEFI boot layout. Installed machines
boot their disk first, so leaving their read-only installation media attached
does not restart the installer. No post-install flag or console work is needed.

Fedora's DVD also stores GRUB menus inside its hidden EFI image. The builder
updates both mirrored menus in that private copy, retaining FAT file sizes and
allocation. It replaces the appended EFI partition and verifies both EFI boot
records against the updated image. Unknown layouts or oversized menus fail
before upload. The pinned source image remains unchanged.

The bootstrap account has key-only SSH and password-free sudo. Root and user
passwords stay locked. Private keys and real passwords never enter an ISO or
Terraform input. A public-key format check rejects private-key files before
apply. The readiness check probes SSH until the installed OS passes every
check. This permits Ubuntu's live installer and installed OS to have different
host keys. It then pins the installed key in a UUID-specific file and records
a protected `verified.json`. Later checks retain that pin. Verification times
out after 30 minutes instead of accepting an incomplete installation.
For UEFI, it also requires 64-bit EFI firmware, a mounted FAT EFI partition,
EFI bootloader files, persistent boot entries, and the declared Secure Boot
state. Enabled Secure Boot additionally requires enrolled PK, KEK, and db
variables, disabled Setup Mode, active shim validation, and kernel lockdown
in integrity or confidentiality mode. A firmware flag alone cannot pass.

Keep controller `artifacts/iso-install/` protected. It contains source caches,
per-VM images, manifests, known-host keys, and verification evidence. Derived
media includes network settings and account policy even though it contains no
password or private key. Never publish these images or answer files through
the ISO web server. Allow source-cache space, one full image per VM, build
workspace, and twice each concurrent image size for the provider's upload.
`-parallelism=2` limits simultaneous builds/uploads and installations.

Installation inputs are creation-only: use a new entry for another machine.
Existing images are immutable and checksum-checked before reuse. Builder
updates affect newly declared VMs. Post-install software and account changes
belong in Ansible. The original manual `debian-install.tf` test and its examples
remain available as historical test fixtures, disabled locally.

Deletion guards protect the new VMs and derived media. After explicit cleanup
authorization, require a saved plan that affects only the intended test
resources. The scoped upload token lacks PVE's storage-wide `Datastore.Allocate`
right required to delete ISO files. An administrator must remove only the
unreferenced, checksum-matched derived image after its VM is gone, then refresh
Terraform. Restore temporary guard overrides afterward. Original media must
remain outside cleanup.

All three profiles passed live automatic installation on 2026-10-26:

| Profile | Installer version | BIOS installation | UEFI installation and cold boot | Secure Boot validation |
|---|---|---|---|---|
| Debian netinst | 13.6 | Passed | Passed | Passed |
| Ubuntu live-server | 26.04 | Passed | Passed | Passed |
| Fedora Server DVD | 44 | Passed | Passed | Passed |

Each test verified disk boot, SSH identity, locked accounts, disabled password
and root SSH login, an active guest agent, and zero failed systemd units.
Every installation completed without console answers. Ubuntu also completed
its installer security updates. Each UEFI test emptied the CD drive and used
Terraform to stop and start the VM with only its system disk in the boot order.
All three passed verification again with a new kernel boot ID, the same machine
UUID, unchanged EFI variables disk, mounted FAT EFI partition, and EFI loaders.
A plan-only conversion test independently confirmed that the VM deletion guard
blocks firmware changes before apply.

Each disposable VM reused the next free VMID and was removed afterward,
including its EFI disk, system disk, derived Proxmox ISO, and temporary ACLs.
Protected BIOS evidence remains under `artifacts/automatic-*-verified-2026-10-26.json`.
UEFI evidence is under `artifacts/uefi-*-coldboot-verified-2026-10-26.json`.
Existing guest hardware, placement, power state, and original media remained
unchanged. Desktop/live-workstation editions and TPM provisioning remain unverified.

Secure Boot validation includes a successful signed installation and a cold
boot with an empty CD drive. The rejection test then clears only the PE
certificate directories from GRUB copies on that disposable VM's EFI partition.
It retains the executable sections and preserves backups inside the test VM.
An explicit signature/security error and an unreachable installed OS are
required before cleanup. Original ISOs and existing guests stay outside this test.

All three passed Secure Boot installation and disk-only cold boots on 2026-10-26.
Each reported active Secure Boot, disabled Setup Mode, enrolled PK/KEK/db keys,
active shim validation, kernel integrity lockdown, and zero failed systemd units.
Each then rejected its unsigned GRUB copies with
`Verification failed: (0x1A) Security Violation`. Read-only screenshots confirmed
the rejection. No console answers, MOK enrollment, or validation bypass were used.
The test guests and all their disks, derived Proxmox ISOs, and temporary ACLs
were removed afterward. A plan-only test confirmed that the VM deletion guard
blocks an in-place Secure Boot policy change before apply.

Protected evidence is under `artifacts/secureboot-*-coldboot-verified-2026-10-26.json`
and `artifacts/secureboot-*-negative-enforcement.json`, with rejection screenshots
beside them. The final comparison preserved all 32 original guests and 55
cached media files, with 121 managed resources and a no-change Terraform plan.

Run the builder and readiness regression tests from `terraform/proxmox/`:

```sh
python3 -m unittest discover -s tests -p 'test_iso_install.py' -v
terraform test
```

The Python tests use xorriso and small generated ISO fixtures. They do not
download installers or connect to guests. Terraform tests use a mock provider.

References: [Debian preseed](https://www.debian.org/releases/trixie/amd64/apbs04.en.html),
[Ubuntu autoinstall](https://canonical-subiquity.readthedocs-hosted.com/en/latest/tutorial/providing-autoinstall.html),
[Fedora Kickstart](https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html),
[xorriso boot-image replay](https://wiki.debian.org/RepackBootableISO).

Secure Boot references: [Debian](https://wiki.debian.org/SecureBoot),
[Ubuntu](https://documentation.ubuntu.com/security/security-features/platform-protections/secure-boot/),
[Fedora](https://fedoraproject.org/wiki/Secureboot),
[PE certificate table](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format#the-attribute-certificate-table-image-only).

### Imported platform resources

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

### LibreSpeed LAN test guest

Use `guest-librespeed.profile.json.example` with `app: librespeed` for a
Debian 13 LXC. The workflow routes application configuration to
`proxmox/librespeed-guests.yml`. An unprivileged LXC shares the host kernel and
avoids a separate VM kernel or nested Docker network. A direct private HTTP
connection also avoids a reverse proxy and TLS processing in the test path.

The example uses the existing two-core, 2 GiB, 8 GiB defaults. For multi-gigabit Ethernet,
four cores provide additional capacity for concurrent PHP test streams.
The guest has no configured network rate limit. See the LibreSpeed section in
`proxmox/README.md` for measurement limits and application settings.
