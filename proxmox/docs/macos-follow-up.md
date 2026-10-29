# Atlas development VM follow-up

Status: the user requested retirement of VM 108 on 2026-10-29.
Existing PBS and S3 backups are preserved. Local PBS retention still applies.
The development and recovery results below are historical records.

## Retirement verified — 2026-10-29

Terraform removed VM 108, its four managed disks, and `macos-dev-hourly`.
The clean shutdown timed out after 180 seconds. The VM was stopped before
applying the saved removal plan. No VM 108 disks remain on either node.
HCP state no longer contains the VM or its dedicated backup job.
The six-hour all-guests job has its original exclusion list.

PBS retained 24 completed local macOS snapshots and 51 completed cloud
snapshots at the check. The newest local snapshot is
`vm/108/2026-10-29T20:15:03Z`. The newest completed cloud snapshot at that
check is `vm/108/2026-10-29T10:15:00Z`. An encrypted copy of the newest local
snapshot continues independently. The unscheduled validation job definition
was removed without stopping that task. The nightly cloud job remains enabled.
Original ISO files are preserved. Private Terraform definitions and the
pre-removal state are saved under ignored
`terraform/proxmox/artifacts/macos-retired-20261029/`.

## State before retirement

VM 108 (`macos-tahoe`) runs on Atlas with 8 vCPUs and 32 GiB RAM.
Connect with `ssh atlas-dev` as `pve` at `10.10.40.9`.
The laptop SSH alias uses the configured SSH agent key selected by
`~/.ssh/lxc.pub`. Private keys remain in the configured agent. See the
migration exclusions below for credential handling.
Automatic VM startup is enabled. Guest `sleep` and `disksleep` are both zero.
The 512 GiB disk now has a 549546057728-byte APFS container. The first
post-growth check reported about 485 GiB available.

The October 28 Atlas maintenance moved VM 108 to Prometheus. Graceful shutdown
timed out, so the user approved a forced stop. OpenCore and recovery media now
use `helios:vm-108-disk-3` (`sata0`) and `helios:vm-108-disk-4` (`sata2`). Both
copies matched the original ISO files byte for byte. The original files remain
on Atlas. The macOS login screen passed visual verification after migration.
QEMU reported unsupported CPU feature warnings on Prometheus. Application
behavior and authenticated SSH remain unverified after this migration.

The later October 28 Prometheus maintenance returned VM 108 to Atlas. Its
clean shutdown again timed out, and the user approved another forced stop.
All four managed ZFS disks migrated successfully. The macOS login screen
passed visual verification on Atlas. The ignored Terraform definition now
matches its Atlas placement and retains the managed boot disks.

Node 24.22.1, Python 3.13.17/uv, Git/Git LFS, GitHub CLI, Ansible,
ansible-lint, CMake, Ninja, tmux, jq, and ripgrep are available.
VS Code 1.143.1 and Zed 1.25.3 are installed in `/Users/pve/Applications`.
Zed on the laptop opened `/Users/pve/Developer/START-HERE.md` through SSH.
Git commits, HTTPS Git access, Node, Python, C, C++17, CMake/Ninja builds,
and Ansible's Proxmox dependencies passed runtime checks. A detached tmux
session survived an SSH disconnect. The remote bootstrap repeat run reported
`changed=0`. The laptop Developer directory is now copied to the VM.

## 1. GPT and APFS growth completed

The user shut down VM 108 through authenticated SSH. Proxmox confirmed it
stopped. A native Proxmox configuration lock protected the offline repair.
`sgdisk --move-second-header` moved the secondary GPT to the 512 GiB disk end.
The disk GUID, both complete partition entries, the full EFI payload, and the
first 16 MiB of APFS remained unchanged. `sgdisk --verify` found no problems.
The existing partition alignment warnings were not changed.

Recovery metadata is on Atlas at
`/root/macos108-gpt-grow-20261024T052351Z/`. It includes raw GPT sectors,
`partition-table.gpt`, pre/post table JSON, and payload checksums.
These pre-growth metadata files must not replace the current partition map
after APFS growth. Restoring the old map would truncate the grown filesystem.

After boot, `diskutil apfs resizeContainer disk0s2 0` verified the filesystem
with exit code zero and expanded APFS from 137229197312 to 549546057728 bytes.
SSH, the development smoke test, and disabled sleep settings passed afterward.
The temporary `~/dev-host-admin.sh` was renamed to `.sh.retired` and made
non-executable. No EFI erase or forced production shutdown was performed.

## 2. Code migration completed

The user authorized the Developer copy after disk repair. Laptop originals
remain intact. The copy preserved `.git`, branches, stashes, uncommitted and
untracked work, and included ignored project configuration. A full checksum
comparison matched 5,351 regular files and seven symlinks, totaling
1,129,806,933 bytes. HEAD, refs, stashes, and working-tree state matched for
all 14 Git repositories after the documented exclusions.

Excluded caches: `node_modules`, `.venv`, `__pycache__`, `.cache`, `.DS_Store`,
and the downloaded `HomelabAnsible/.ansible` collection cache.
Excluded credential files:

- `ProxmoxMCP/proxmox.json`
- `HomelabAnsible/proxmox/files/gallery-dl-cookies.txt`
- `docker-wyze-bridge/app/.env`

The first two files were initially copied, then removed when the exclusion
audit found them. Their exclusions were added before the new manual backup.
The Wyze `.env` is tracked. Its absence appears as a deletion on the VM and
must not be committed as an intentional code change.

GitHub CLI is not authenticated. Account sign-ins, private certificates,
signing keys, and excluded credentials need separate user action. Keep private
SSH keys in the configured agent. On a replacement laptop, restore agent
access through Bitwarden and recreate the documented SSH alias.

## 3. Prove recovery

Before retirement, the dedicated `macos-dev-hourly` job backed up VM 108
at :15 each hour to storage `mnemosyne`. That job is retired with the VM.
The six-hour all-guests job retains its original selection and retention rules.
Relevant recovery points on PBS datastore `mneme`, namespace `cluster-nash`:

- `vm/108/2026-10-24T04:11:32Z`: first VM backup. PBS verified every included
  image and the configuration with zero errors (`TASK OK`).
- `vm/108/2026-10-24T04:40:50Z`: development setup backup, completed at
  23:43:45 Central on October 23. It includes the 512 GiB backing disk and
  installed tools. It predates successful APFS expansion.

A new `vm/108/2026-10-24T05:29:23Z` backup completed at 00:33:54 Central
on October 24. It includes the expanded filesystem and migrated code.
PBS verified every included disk and the configuration with zero errors
(`TASK OK`). A full restore into temporary VM
114 completed in about 2.5 minutes. Its network was removed and automatic
startup was disabled before the isolated boot test. The restored VM reached
the macOS login screen. Only the temporary VM and its four scratch disks were
removed afterward. Production VM 108 stayed running. This test used Atlas,
not a different CPU or Proxmox node.

These backups include the system disk, EFI disk, and attached OpenCore/recovery
images, because those images are presented as disks. The older `ct/108`
backups belong to a retired container. Select `vm/108` for macOS recovery.
The second snapshot has not had a separate full verification pass.
A recovered-file test has not been performed. These backups do not freeze the
guest filesystem and are not proof of application-consistent recovery.
PBS is another homelab machine, not an offsite copy.

## 4. Resolve editor and project compatibility as needed

A Swift Metal API check returned `No Metal device`. The VM has no GPU
passthrough. Zed's GUI requires Metal, so use laptop Zed with the verified
SSH workflow. Native graphical Zed operation inside this VM is not verified.
Any GPU passthrough plan needs a separate hardware and host-impact review.
Do not change shared host GPU or boot settings as a shortcut.

Intel macOS Homebrew is Tier 3. CMake, tmux, and dependencies successfully
built from source. Vendor tools use pinned archives and checksums in
`mac/dev-tools.yml`. Keep version and checksum updates together.
Mineways' source Makefile hardcodes ARM64 flags. Homebrew built wxWidgets
3.3.4 and its missing Intel dependencies from source. An isolated validation
copy at `~/Builds/Mineways-intel` uses `Mac/Makefile.intel` to substitute
`-arch x86_64` in the compiler and linker flags. The native executable built,
and the complete port regression test passed. The application bundle is at
`~/Applications/Mineways.app`. GUI interaction remains untested.
The migrated `~/Developer/Mineways` working tree remains unchanged.
The remote development playbook now includes wxWidgets as a dependency.

The four archive projects passed Node tests. BoughtThenBuried and
KilledByAmazon built successfully. ProxmoxMCP installed its locked dependencies
and passed all five offline tests. AppleModels built and passed material
reference checks. The observer passed 31 offline tests. `mcrcon` compiled
natively for Intel and reported version 0.7.2. Browser and VR behavior remain
untested. Full Xcode and a container runtime are not installed.
Install project-specific dependencies after identifying the required work.

## 5. Keep the other diagnosed issues separate

The last network tests measured 6.08 Gbit/s upload and 0.898 Gbit/s download.
ACK tuning provided no useful improvement. Disabling TSO reduced upload to
0.454 Gbit/s. Original settings were restored and verified. The receive
bottleneck remains unconfirmed. Temporary PBS test access and the server
were removed. Do not retain the unsuccessful tuning changes.

Direct laptop SSH briefly timed out during the October 24 backup. Atlas could
reach the guest, and SSH through Atlas succeeded. Direct SSH later recovered
without a configuration change. The cause remains unconfirmed.

Earlier installation work also found Forgejo's full filesystem and 219
unintended secondary IPv4 addresses. Approved cleanup preserved its primary
address and service. The secondary-address cause and full filesystem need
their own investigation. See `macos.md` for saved recovery metadata and the
verification boundary. Do not combine that work with VM disk repair.
