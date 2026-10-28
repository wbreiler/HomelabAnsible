# macOS provisioning

Two independent Ansible roles provision an Apple silicon Mac locally with
`/opt/homebrew`. The development role also supports a remote Intel macOS VM
with `/usr/local` through `dev-vm.yml`. Neither role removes the other role's software.

| Role | Purpose | Managed areas |
| --- | --- | --- |
| `mac_main` | Everyday personal Mac | Personal Homebrew apps, App Store apps, 1Password SSH configuration, Dock, desktop defaults, Touch ID |
| `mac_dev` | Dedicated development Mac or Intel VM | Build tools, language runtimes, Codex, Chrome and editors, shell, Git, homelab SSH/public keys, optional SSH server and Screen Sharing, desktop startup, AC power settings |

Each role installs Command Line Tools and Homebrew when absent. Package lists
are in `roles/mac_main/defaults/main.yml` and `roles/mac_dev/defaults/main.yml`.
The minimal Intel bootstrap remains separate in `dev-host.yml`.
Use `dev-vm.yml` for the full development role. See [DEV-HOST.md](DEV-HOST.md).

For a fresh dedicated Mini, follow [MINI-BOOTSTRAP.md](MINI-BOOTSTRAP.md).
It covers tool installation, transfer of unpushed commits, manual sign-ins,
and restart/cold-boot checks. Use `make run-dev REMOTE_ACCESS=true` with the hosts task enabled.

## Choose a role

Install Ansible on the target Mac as its normal development user. Complete
macOS Setup Assistant first. Use an administrator account for sudo tasks.

```bash
cd mac
make install
make check PROFILE=dev REMOTE_ACCESS=true
make run-dev REMOTE_ACCESS=true # Dedicated Mac Mini
```

Other selections:

```bash
make run-main                 # Everyday Mac, also the default for make run
make run-both                 # Everyday Mac plus development tools
make check PROFILE=both
make run-tags PROFILE=dev REMOTE_ACCESS=true TAGS=remote_access
```

`make run` now selects only `main`. Use `make run-both` for the old combined
software selection. Local runs keep SSH outbound-only. Set `REMOTE_ACCESS=true`
for incoming SSH, Screen Sharing, and the dedicated AC power policy. A combined run applies
`mac_dev` last. With remote access enabled, the dev role records a marker at
`/Library/Application Support/HomelabAnsible/mac-dev`. Later main-role runs
preserve the dev sleep policy. A combined run also skips personal sleep settings
before that marker exists.

Direct invocation also supports both roles:

```bash
ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["main","dev"]}'
```

Tags retain their previous names. Main tags are `xcode`, `homebrew`, `mas`,
`ssh`, `dock`, `defaults`, and `macos`. Dev tags are `xcode`, `homebrew`, `shell`,
`ssh`, `git`, `hosts`, `startup`, and `remote_access`. Select `PROFILE=dev` or
`PROFILE=both` when using dev tags.

## Intel development VM

Run the full role from this directory on the controller. The SSH alias must
identify the VM and its normal development user. For the existing Atlas VM:

```bash
ansible-playbook -i 'dev_host,' dev-vm.yml -e ansible_host=atlas-dev -u pve --ask-become-pass --check --diff
# Apply only after reviewing the changes and approving the live run:
ansible-playbook -i 'dev_host,' dev-vm.yml -e ansible_host=atlas-dev -u pve --ask-become-pass
```

This entry point rejects localhost, local connections, root, and non-Intel
targets. It imports only `mac_dev`. Its apps use `~/Applications`, matching
the existing VM installation. Shell, Homebrew, readiness checks, and
desktop startup use native Intel paths. The local `main.yml` retains its
Apple silicon guard and `/Applications` default.

Intel does not install ARM-only `container-compose`. Docker CLI
tools remain available for a separately configured remote engine. Packages
without compatible bottles can require source builds and extra disk space.
Homebrew failures stop the role rather than silently skipping development tools.

The role installs Chrome and copies `~/Developer/BROWSER-SETUP.md`. Install the
official ChatGPT extension through **Settings > Computer Use**, review its
permissions, and confirm Chrome shows **Manage**. Account sign-in, device
pairing, browser site permissions, and macOS privacy consent remain manual.
The role does not copy authenticated profiles or modify the TCC database.

This is a full provisioning role. It backs up and replaces shell
configuration, manages homelab SSH access, edits hosts, and enables remote
services. Review the complete diff before applying it to an existing VM.

## Dedicated Mac Mini access

With `REMOTE_ACCESS=true`, the local dev role enables Remote Login with `systemsetup` and enables the native
Screen Sharing launch service. It creates missing access groups and adds the
current user. Existing allowed users remain. It does not enable a shared VNC
password or copy private keys. It installs all six public key selectors from
`files/ssh_public_keys/` and the homelab SSH client configuration. The cluster
public key grants incoming access through a managed `authorized_keys` block.
Existing keys remain. Override `mac_dev_authorized_key_files` to select other
tracked public key filenames. Review existing access lists in Sharing settings.

macOS can require consent that Ansible cannot grant. Before an unattended run,
grant the terminal Full Disk Access if `systemsetup` requires it. If Screen
Sharing does not permit control, complete the following once at the Mac:

1. Open **System Settings > General > Sharing**.
2. Disable **Remote Management** if it is enabled.
3. Enable **Screen Sharing**.
4. Select **Only these users** and add the development account.
5. Verify **Remote Login** permits the development account.

Apple documents the access controls in its [Screen Sharing guide](https://support.apple.com/guide/mac-help/turn-screen-sharing-on-or-off-mh11848/mac)
and [Remote Login guide](https://support.apple.com/guide/mac-help/allow-a-remote-computer-to-access-your-mac-mchlp1066/mac).
Screen Sharing and Remote Management cannot operate together.

From another Mac on the trusted LAN or VPN, use `ssh <user>@<mac-address>` for
the terminal. Open `vnc://<mac-address>` in Finder's **Go > Connect to Server**
to use Screen Sharing. Authenticate with the development account. No router
port forwards or firewall bypasses are installed.

The dev role disables system sleep on AC power and enables network wake and
restart after power loss. It preserves display sleep and battery settings.
FileVault remains enabled if already configured. Apple silicon with macOS 26+
supports SSH FileVault unlock after restart when networking is available. Test
cold boot separately. Follow [MINI-RECOVERY.md](MINI-RECOVERY.md) before treating
the Mac as unattended infrastructure. The role also copies that guide to
`~/Developer/MINI-RECOVERY.md`. The bootstrap guide is copied alongside it as
`~/Developer/MINI-BOOTSTRAP.md`. The address audit is also copied there as
`HOSTS-AUDIT.md`.

The role installs the Codex CLI and the ChatGPT desktop host. A user login agent
opens `/Applications/ChatGPT.app` after graphical login. It loads the agent
immediately when a graphical session exists. Otherwise, the next desktop login
loads it. Sign into the desktop app, pair Remote Control, and run `codex login`
once. Complete macOS privacy prompts through Screen Sharing. The role does not
enable automatic macOS login. A restart still requires desktop login before Remote
Control returns.

The role also installs Chrome and a browser setup guide in `~/Developer/`.
Browser extension permissions require the user's direct consent.

1Password is included for outbound Git and homelab authentication. Enable its
SSH agent and unlock it after login. Incoming SSH needs only the trusted public
key and the controller agent. A local 1Password socket takes precedence when
present. Otherwise, the SSH config preserves the default or forwarded agent.
Private keys, passwords, tokens, and authenticated sessions are never copied.

## Files and existing behavior

The dev role renders `.zshrc` and `.zprofile` from templates,
with backups of existing files.
It configures the existing Git identity and creates `~/Developer`. Its shell
preserves a forwarded SSH agent unless a local 1Password socket exists.
Review the static hosts in `roles/mac_dev/tasks/hosts.yml` before applying them.
The [2026-10-24 address audit](HOSTS-AUDIT.md) records two corrected addresses,
the Seerr compatibility alias, and the DHCP/retirement follow-up. Five obsolete
aliases were removed. The user confirmed that Gallery and Cobbleverse are no
longer live, resolving the final two uncertain entries. Deluge
uses the TrueNAS app address `10.10.20.3`. The Erebus management alias uses
`10.10.10.7`.

The main role replaces `~/.ssh/config` with a backup and preserves
`~/.config/1Password`. It requires App Store sign-in for MAS apps.
Its Dock task removes the current layout. Its defaults retain the existing
MacBook computer names, power policy, and UI restarts. Review these files before
applying main to another machine. Personal package loops still tolerate failures.
Dev Homebrew package failures stop the play.

Obtain explicit approval immediately before any live application. No live run
is part of a code change. Check mode can be incomplete when required software
is absent. It does not establish convergence.

## Validation

```bash
cd mac
make validate
```

After an authorized dedicated-host installation, run `~/Developer/mac-dev-check.sh` on the
Mac. Then verify SSH authentication and Screen Sharing control from another Mac.
The check verifies CLI sign-in, the desktop app and login agent, public keys,
access groups, and the AC power policy. It cannot prove network reachability,
Screen Sharing control, desktop sign-in, or Remote Control pairing. The recovery
guide supplies the external checks and separate restart/cold-boot procedures.

Retired package entries no longer install Docker completion, Claude, Claude Code,
VS Code, rar, OrbStack, MarkEdit, or TimeMachineStatus. Existing installations
and editor settings remain untouched. 1Password replaces Bitwarden in both profiles.
