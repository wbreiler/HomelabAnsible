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
ripgrep, VS Code, and Zed. It may build Intel dependencies from source.
Editors install into the user's Applications directory.

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
Private keys, GitHub tokens, signing certificates, and laptop account tokens
were not transferred. Container runtimes and full Xcode are not installed.
Mineways currently hardcodes ARM64 flags, so its existing Mac build needs an
architecture review before it can build on this Intel VM.

## Protection and later migration

VM 108 starts with Atlas. `proxmox/macos.yml` creates new VMs with 8 vCPUs,
32 GiB RAM, and a 512 GiB system disk. It preserves existing VM settings.
The current backing disk is 512 GiB, but its APFS filesystem remains 128 GiB.
The user deferred GPT repair and filesystem growth. See
[`proxmox/docs/macos-follow-up.md`](../proxmox/docs/macos-follow-up.md) before
resuming that work. Guest sleep and disk sleep are disabled.
The `macos-dev-hourly` job backs up only VM 108 to Mnemosyne at :15 each hour.
It does not prune. The existing all-guests job also runs every six hours at
:30 and retains 12 hourly, 14 daily, 8 weekly, 12 monthly, and 2 yearly points,
plus its keep-last rule. Missed or failed backups can leave older recovery
points. The first VM backup passed PBS chunk verification with zero errors.
Its attached OpenCore and recovery images are included as disks in the backup.
This is a snapshot backup without guest filesystem freeze. It does not prove
a full restore or application consistency. PBS is a separate homelab machine,
not an offsite copy.

Code migration was explicitly deferred. Keep laptop originals when copying
later. Preserve `.git`, local branches, stashes, untracked files, and required
ignored configuration. Exclude only verified rebuildable caches. Compare the
copy, run actual project builds, and create a new backup before declaring the
migration complete. Do not infer project coverage from the bootstrap smoke test.

If Atlas fails, restore the `vm/108` backup group from namespace `cluster-nash`
on PBS datastore `mneme` through Proxmox. Do not select the older `ct/108`
group, which belongs to a retired container. Confirm restored MAC/IP ownership
and boot disk mappings before starting a replacement on the network.
