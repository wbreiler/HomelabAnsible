# Atlas development VM follow-up

Status: deferred by the user on 2026-10-23. This is a work note, not a scheduled
task or permission to resume disruptive work. VM 108 remains running.

## Current working state

VM 108 (`macos-tahoe`) runs on Atlas with 8 vCPUs and 32 GiB RAM.
Connect with `ssh atlas-dev` as `pve` at `10.10.40.9`.
The laptop SSH alias uses the existing Bitwarden agent key selected by
`~/.ssh/lxc.pub`. No private key or account token was transferred.
Automatic VM startup is enabled. Guest `sleep` and `disksleep` are both zero.
The physical virtual disk is 512 GiB, but APFS remains 128 GiB with about
101 GiB available. Do not report the extra space as usable yet.

Node 24.22.1, Python 3.13.17/uv, Git/Git LFS, GitHub CLI, Ansible,
ansible-lint, CMake, Ninja, tmux, jq, and ripgrep are available.
VS Code 1.143.1 and Zed 1.25.3 are installed in `/Users/pve/Applications`.
Zed on the laptop opened `/Users/pve/Developer/START-HERE.md` through SSH.
Git commits, HTTPS Git access, Node, Python, C, C++17, CMake/Ninja builds,
and Ansible's Proxmox dependencies passed runtime checks. A detached tmux
session survived an SSH disconnect. The remote bootstrap repeat run reported
`changed=0`. No laptop repositories were migrated.

## 1. Finish GPT and APFS growth

The hypervisor and macOS physical disk both report 549755813888 bytes.
The partition map still records `last-lba: 268435422`, the old 128 GiB
boundary. Its identity is `249EC074-929D-4F96-9FB2-C9CBC59767EC`.
The APFS partition starts at sector 409640, has 268025776 sectors, and has
UUID `9352F656-4AE7-4057-8C8C-A3BBE01EAA45`.
The EFI partition starts at sector 40 and has 409600 sectors.
The backing volume is `helios/vm-108-disk-2` on Atlas.

`diskutil verifyDisk disk0` reported a healthy map. APFS limits report a
549545029632-byte maximum, but automatic growth returns error -69743
(new size equals existing size). An explicit maximum is rejected as larger
than the map's allocatable space. Read-only host `sfdisk --dump` exposed the
old GPT boundary. Neither attempt changed the partition sizes.

Resume with a fresh state check and a current backup. Arrange a graceful
shutdown of only VM 108 and confirm Proxmox reports it stopped. Save the GPT
and partition entries before using `sgdisk -e` on its backing volume to move
the backup header to the actual disk end. `sgdisk` 1.0.10 is installed on Atlas.
Preserve both partition starts, sizes, GUIDs, and the EFI payload. Verify the
map before starting the VM. Then expand its existing APFS container and verify
the actual filesystem capacity. Create a new backup after the completed grow.
Do not alter the raw partition map while this VM is running.

The native `diskutil repairDisk` prompt warns it might erase `disk0s1`.
That repair was explicitly canceled. Do not automatically answer yes.
`~/dev-host-admin.sh` disabled sleep but did not complete disk growth. Its
success label is not a postcondition check. Replace or retire that temporary
helper before any future use. No GPT repair, EFI erase, or forced shutdown
was performed. The user deferred the requested full power-off.

## 2. Migrate code only after the user resumes that work

The user explicitly selected preparation first and code transfer later.
The inspected laptop `~/Developer` directory was 1.2 GiB. Preserve laptop
originals. Include `.git`, branches, stashes, uncommitted changes, untracked
files, and required ignored configuration. Review cache exclusions instead
of excluding all ignored files. Verify the destination and build actual
projects before switching daily work. Back up the migrated data before
considering the migration complete.

GitHub CLI is not authenticated. Account sign-ins, private certificates,
signing keys, and other credentials need separate user action. Keep private
SSH keys in the configured agent. On a replacement laptop, restore agent
access through Bitwarden and recreate the documented SSH alias.

## 3. Prove recovery

The dedicated `macos-dev-hourly` job backs up only VM 108 at :15 each hour
to storage `mnemosyne`. It does not prune. The existing six-hour all-guests
job retains its existing selection and retention rules.
PBS datastore `mneme`, namespace `cluster-nash`, contains these VM snapshots:

- `vm/108/2026-10-24T04:11:32Z`: first VM backup. PBS verified every included
  image and the configuration with zero errors (`TASK OK`).
- `vm/108/2026-10-24T04:40:50Z`: development setup backup, completed at
  23:43:45 Central on October 23. It includes the 512 GiB backing disk and
  installed tools. It predates successful APFS expansion, which is deferred.

Both backups include the system disk, EFI disk, and attached OpenCore/recovery
images, because those images are presented as disks. The older `ct/108`
backups belong to a retired container. Select `vm/108` for macOS recovery.
The second snapshot has not had a separate full verification pass.
No full VM restore or recovered-file test was performed. Test a restore in
isolation to prevent duplicate MAC/IP use. These backups do not freeze the
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
Mineways' current Mac Makefile hardcodes ARM64 flags and needs an Intel
architecture review. Actual project builds remain untested because code
migration is deferred. Full Xcode and a container runtime are not installed.
Install project-specific dependencies after identifying the required work.

## 5. Keep the other diagnosed issues separate

The last network tests measured 6.08 Gbit/s upload and 0.898 Gbit/s download.
ACK tuning provided no useful improvement. Disabling TSO reduced upload to
0.454 Gbit/s. Original settings were restored and verified. The receive
bottleneck remains unconfirmed. Temporary PBS test access and the server
were removed. Do not retain the unsuccessful tuning changes.

Earlier installation work also found Forgejo's full filesystem and 219
unintended secondary IPv4 addresses. Approved cleanup preserved its primary
address and service. The secondary-address cause and full filesystem need
their own investigation. See `macos.md` for saved recovery metadata and the
verification boundary. Do not combine that work with VM disk repair.
