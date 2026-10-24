# macOS provisioning

Two independent Ansible roles provision an Apple silicon Mac locally. Both use
`/opt/homebrew`. Neither role removes software installed by the other role.

| Role | Purpose | Managed areas |
| --- | --- | --- |
| `mac_main` | Everyday personal Mac | Personal Homebrew apps, App Store apps, Bitwarden SSH configuration, Dock, desktop defaults, Touch ID |
| `mac_dev` | Dedicated Codex/dev Mac Mini | Build tools, language runtimes, Codex and editors, shell, Git, VS Code, homelab hosts, SSH server, Screen Sharing, AC power settings |

Each role installs Command Line Tools and Homebrew when absent. Package lists
are in `roles/mac_main/defaults/main.yml` and `roles/mac_dev/defaults/main.yml`.
The existing Intel remote playbook remains separate. See [DEV-HOST.md](DEV-HOST.md).

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
`mac_dev` last, so its AC sleep settings take precedence. After a separate main
run on a dev Mac, reapply `make run-tags PROFILE=dev TAGS=remote_access` because
main defaults restore the personal sleep policy.

Direct invocation also supports both roles:

```bash
ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["main","dev"]}'
```

Tags retain their previous names. Main tags are `xcode`, `homebrew`, `mas`,
`ssh`, `dock`, `defaults`, and `macos`. Dev tags are `xcode`, `homebrew`, `shell`,
`git`, `vscode`, `hosts`, and `remote_access`. Select `PROFILE=dev` or
`PROFILE=both` when using dev tags.

## Dedicated Mac Mini access

The dev role enables Remote Login with `systemsetup` and enables the native
Screen Sharing launch service. It creates missing access groups and adds the
current user. Existing allowed users remain. It does not enable a shared VNC
password or copy private keys. Review existing access lists in Sharing settings.

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
FileVault remains enabled if already configured. A cold boot can require a
local disk unlock before SSH or Screen Sharing becomes available. Test recovery
with physical access before treating the Mac as unattended infrastructure.

Sign into Codex and other apps through Screen Sharing. Complete any macOS
privacy prompts there. The role does not copy authentication tokens, enable
automatic login, or require Bitwarden for incoming SSH. Add trusted public keys
to `~/.ssh/authorized_keys` separately if key authentication is desired.

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
The local smoke check cannot prove network reachability or graphical control.
