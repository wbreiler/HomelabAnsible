# Dedicated macOS development host

`dev-host.yml` prepares an existing remote Intel Mac without running the
Apple-silicon localhost reset playbook. It preserves the existing shell files
and adds a managed PATH block. It does not migrate repositories or credentials.

From `mac/`, after authorizing the target:

```bash
ANSIBLE_LOCAL_TEMP=/private/tmp/ansible-dev-host ansible-playbook \
  -i 'dev_host,' dev-host.yml -u pve --private-key ~/.ssh/lxc.pub \
  -e ansible_host=10.10.40.9 -e ansible_python_interpreter=/usr/bin/python3
```

Supply optional `dev_git_name` and `dev_git_email` variables through an untracked
local variables file to set the Git author. No identity or credential is embedded
in this playbook. Install `requirements.yml` on the controller first.
Use `--check --diff` for a dry run. Vendor downloads/extraction are skipped in
check mode because their destination directories may not exist yet. A real run
and the smoke test establish runtime behavior.

The playbook installs checksum-pinned Intel vendor binaries for Node 24.22.1,
uv 0.13.5, GitHub CLI 2.103.2, Git LFS 3.8.1, CMake 4.4.4, and Ninja 1.13.2.
They live under `~/.local/share/dev-tools`, with links under `~/.local/bin`.
Update the version and checksum together. Python 3.13 is managed by uv.
Ansible and ansible-lint use isolated uv tool environments. Existing system Git
and the Command Line Tools provide the compiler. Homebrew manages tmux, jq,
ripgrep, VS Code, and Zed. It may build Intel dependencies from source. A repeat run with wxWidgets
installed reported `changed=0`, with no failed or unreachable tasks.
Editors install into the user's Applications directory. The remote package
list also includes wxWidgets for native Mineways builds.

`dev-host-check` creates a temporary directory, tests a local Git commit,
executes Node and Python, and compiles C with both clang and CMake/Ninja.
It removes only its temporary directory. It does not test actual project builds.
The setup guide is installed as `~/Developer/START-HERE.md` only when absent.

## Client workflow

Use `ssh atlas-dev` from a client with this SSH alias:

```sshconfig
Host atlas-dev
    HostName 10.10.40.9
    User pve
    IdentityFile ~/.ssh/lxc.pub
    IdentitiesOnly yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

The controller's original SSH configuration was preserved before adding this
alias. Its key remains in the configured Bitwarden SSH agent. On a replacement
client, install the agent, restore access to the existing key through Bitwarden,
and recreate this alias. Do not copy private keys from another machine.

Zed's **File > Open Remote** accepts `ssh atlas-dev`. Open
`/Users/pve/Developer`. Files and builds remain on the VM while the editor runs
on the client. This avoids relying on the VM's unaccelerated display.
Keep workspace trust decisions scoped to code you reviewed.
Use `ssh -t atlas-dev tmux new -As dev` for a persistent terminal. Detach with
Ctrl-B, D. The same command reconnects to that session.

GitHub CLI and other account-based tools still require a separate user sign-in.
Private SSH keys remain in the configured agent. Recreate excluded account
credentials on the VM only when needed. Container runtimes and full Xcode
are not installed.
Mineways' source Makefile hardcodes ARM64 flags. The separate Intel validation
build and its architecture overrides are documented below.

## Protection and migration

VM 108 starts with Atlas. `proxmox/macos.yml` creates new VMs with 8 vCPUs,
32 GiB RAM, and a 512 GiB system disk. It preserves existing VM settings.
GPT repair and APFS growth completed on 2026-10-24. The APFS container now
uses 549546057728 bytes, with about 485 GiB initially available.
The offline repair preserved both partition entries and verified the complete
EFI payload and APFS prefix. Guest sleep and disk sleep are disabled.
The `macos-dev-hourly` job backs up only VM 108 to Mnemosyne at :15 each hour.
It does not prune. The existing all-guests job also runs every six hours at
:30 and retains 12 hourly, 14 daily, 8 weekly, 12 monthly, and 2 yearly points,
plus its keep-last rule. Missed or failed backups can leave older recovery
points. The migrated-code backup passed PBS chunk verification with zero errors.
Its attached OpenCore and recovery images are included as disks in the backup.
This is a snapshot backup without guest filesystem freeze. A full isolated
restore of the migrated-code backup reached the macOS login screen on Atlas.
It does not prove application consistency, recovered-file contents, or boot
on another node. PBS is a separate homelab machine, not an offsite copy.

The user authorized migration on 2026-10-24. The laptop's `~/Developer` was
copied to `/Users/pve/Developer` without deleting or changing laptop originals.
The checksum comparison matched 5,351 regular files and seven symlinks, totaling
1,129,806,933 bytes. All 14 Git repositories retained HEAD, refs, stashes, and
working-tree changes after the documented exclusions.

The copy excluded `node_modules`, `.venv`, `__pycache__`, `.cache`, `.DS_Store`,
and the downloaded `HomelabAnsible/.ansible` collection cache. It also excluded
`ProxmoxMCP/proxmox.json`, `HomelabAnsible/proxmox/files/gallery-dl-cookies.txt`,
and `docker-wyze-bridge/app/.env`. The first two credential files were removed
after the initial copy exposed the missing exclusions. Their laptop originals
remain intact. The Wyze `.env` is tracked and therefore appears as a deletion
in the VM working tree. Do not commit that deletion as a project change.

The four archive projects passed their Node tests. BoughtThenBuried and
KilledByAmazon built successfully. ProxmoxMCP installed its locked dependencies
and passed five offline tests. AppleModels installed its locked dependencies,
built successfully, and verified all model material references. Browser, VR,
and live infrastructure behavior were not tested by these checks. The observer
passed 31 offline tests, and `mcrcon` compiled natively for Intel.

Mineways built natively with wxWidgets 3.3.4 in `~/Builds/Mineways-intel`.
Its complete port regression test passed. `Mac/Makefile.intel` includes the
source Makefile and substitutes `-arch x86_64` in `CXXFLAGS`, `GUI_CXXFLAGS`,
and `LDFLAGS`. The original migrated source remains unchanged. The application
bundle is installed at `~/Applications/Mineways.app`. GUI interaction was not
tested. The validation copy is a snapshot of the migrated source. Refresh it
before building later source edits. Its build command is:

```bash
make -C ~/Builds/Mineways-intel/Mac -f Makefile.intel -j8 all test app
```

See [the follow-up note](../proxmox/docs/macos-follow-up.md) for recovery results
and remaining project compatibility work.

If Atlas fails, restore the `vm/108` backup group from namespace `cluster-nash`
on PBS datastore `mneme` through Proxmox. Do not select the older `ct/108`
group, which belongs to a retired container. Confirm restored MAC/IP ownership
and boot disk mappings before starting a replacement on the network.
