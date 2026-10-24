# macOS provisioning

Two independent Ansible roles provision an Apple silicon Mac locally. Both use
`/opt/homebrew`. Neither role removes software installed by the other role.

| Role | Purpose | Managed areas |
| --- | --- | --- |
| `mac_main` | Everyday personal Mac | Personal Homebrew apps, App Store apps, Bitwarden SSH configuration, Dock, desktop defaults, Touch ID |
| `mac_dev` | Dedicated Codex/dev Mac Mini | Build tools, language runtimes, Codex and editors, shell, Git, VS Code, homelab SSH/public keys, SSH server, Screen Sharing, desktop startup, AC power settings |

Each role installs Command Line Tools and Homebrew when absent. Package lists
are in `roles/mac_main/defaults/main.yml` and `roles/mac_dev/defaults/main.yml`.
The existing Intel remote playbook remains separate. See [DEV-HOST.md](DEV-HOST.md).

For a fresh dedicated Mini, follow [MINI-BOOTSTRAP.md](MINI-BOOTSTRAP.md).
It covers tool installation, transfer of unpushed commits, manual sign-ins,
and restart/cold-boot checks. Use `make run-dev` with the hosts task enabled.

## Choose a role

Install Ansible on the target Mac as its normal development user. Complete
macOS Setup Assistant first. Use an administrator account for sudo tasks.

```bash
cd mac
make install
make check PROFILE=dev
make run-dev                  # Dedicated Mac Mini
```

Other selections:

```bash
make run-main                 # Everyday Mac, also the default for make run
make run-both                 # Everyday Mac plus development tools
make check PROFILE=both
make run-tags PROFILE=dev TAGS=remote_access
```

`make run` now selects only `main`. Use `make run-both` for the old combined
software selection plus the new remote-access settings. A combined run applies
`mac_dev` last. The dev role records a marker at
`/Library/Application Support/HomelabAnsible/mac-dev`. Later main-role runs
preserve the dev sleep policy. A combined run also skips personal sleep settings
before that marker exists.

Direct invocation also supports both roles:

```bash
ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["main","dev"]}'
```

Tags retain their previous names. Main tags are `xcode`, `homebrew`, `mas`,
`ssh`, `dock`, `defaults`, and `macos`. Dev tags are `xcode`, `homebrew`, `shell`,
`ssh`, `git`, `vscode`, `hosts`, `startup`, and `remote_access`. Select `PROFILE=dev` or
`PROFILE=both` when using dev tags.

## Dedicated Mac Mini access

The dev role enables Remote Login with `systemsetup` and enables the native
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
`~/Developer/MINI-BOOTSTRAP.md`.

The role installs the Codex CLI and the ChatGPT desktop host. A user login agent
opens `/Applications/ChatGPT.app` after graphical login. It loads the agent
immediately when a graphical session exists. Otherwise, the next desktop login
loads it. Sign into the desktop app, pair Remote Control, and run `codex login`
once. Complete macOS privacy prompts through Screen Sharing. The role does not
enable automatic macOS login. A restart still requires desktop login before Remote
Control returns.

Bitwarden is included for outbound Git and homelab authentication. Enable its
SSH agent and unlock it after login. Incoming SSH needs only the trusted public
key and the controller agent. A local Bitwarden socket takes precedence when
present. Otherwise, the SSH config preserves the default or forwarded agent.
Private keys, passwords, tokens, and authenticated sessions are never copied.

## Files and existing behavior

The dev role replaces `.zshrc`, `.zprofile`, and VS Code settings with backups.
It configures the existing Git identity and creates `~/Developer`. Its shell
preserves a forwarded SSH agent unless a local Bitwarden socket exists.
Review the static hosts in `roles/mac_dev/tasks/hosts.yml` before applying them.

The main role replaces `~/.ssh/config` with a backup and removes the obsolete
`~/.config/1Password` directory. It requires App Store sign-in for MAS apps.
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

After an authorized live installation, run `~/Developer/mac-dev-check.sh` on the
Mac. Then verify SSH authentication and Screen Sharing control from another Mac.
The check verifies CLI sign-in, the desktop app and login agent, public keys,
access groups, and the AC power policy. It cannot prove network reachability,
Screen Sharing control, desktop sign-in, or Remote Control pairing. The recovery
guide supplies the external checks and separate restart/cold-boot procedures.
