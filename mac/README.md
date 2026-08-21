# macOS provisioning

This Apple-silicon-specific playbook provisions a fresh Mac locally: Xcode
Command Line Tools, Homebrew software, App Store apps, shell and editor files,
Git/SSH configuration, homelab hosts, Dock layout, and macOS defaults. It uses
`/opt/homebrew` paths and has no inventory or `ansible.cfg`.

## Bootstrap and run

Install Ansible first. The playbook can install Xcode Command Line Tools and
Homebrew when absent, so they are not separate prerequisites. Sign into the Mac
App Store before running the `mas` tasks.

```bash
cd mac
make install
make check
make run
```

`make install` installs `community.general`. `make run` applies `main.yml` to
`localhost` and prompts for sudo. `make check` is check mode only; command,
Homebrew, MAS, Dock, and defaults tasks may be incomplete or noisy there, and it
does not prove convergence.

To run a subset:

```bash
make run-tags TAGS=homebrew
make run-tags TAGS=defaults,dock
make run-tags TAGS=shell
```

Available tags are `xcode`, `homebrew`, `mas`, `shell`, `git`, `ssh`, `vscode`,
`hosts`, `dock`, `defaults`, and `macos`. Inspect the selected tasks before a
live run: they mutate user or system state, and Dock/defaults tasks visibly
alter the current session.

## Managed areas

| Tag | Current behavior |
| --- | --- |
| `xcode` | Detects and installs Xcode Command Line Tools through `softwareupdate` when absent |
| `homebrew` | Installs/updates Homebrew, taps, formulae, casks, `dockutil`, and sudo Touch ID support |
| `mas` | Installs IDs in `tasks/mas.yml`; requires a signed-in, entitled account and runs installs as root |
| `shell` | Installs Oh My Zsh, replaces `.zshrc`/`.zprofile` with backups, manages pyenv Python 3.14 and selected pip/npm packages, and selects zsh |
| `git` | Sets the global name/email and installs Git LFS hooks; it does not configure commit signing |
| `ssh` | Replaces `~/.ssh/config` with backup and installs 1Password agent configuration; private keys are not managed |
| `vscode` | Replaces VS Code `settings.json` with backup and attempts every extension in `tasks/vscode.yml` |
| `hosts` | Replaces the marked Ansible block in `/etc/hosts` with the tracked homelab entries |
| `dock` | Removes every Dock item, installs the tracked application order and Downloads folder, then restarts Dock |
| `defaults`, `macos` | Applies user/system defaults, power settings, computer names, and restarts Finder/SystemUIServer |

The formula, cask, MAS app, extension, Dock, host, and defaults lists change over
time; their task files are authoritative. Homebrew formula/cask loops and VS
Code extension installation intentionally tolerate individual failures, so a
successful play does not prove every requested item installed.

Homebrew installs `dockutil` before a full run reaches Dock configuration.
The sudo Touch ID bootstrap runs its binary with privilege, but its Homebrew
service starts as the normal user; do not start `brew services` under sudo.

## Files and safety

Tracked files under `files/` replace these user files:

- `~/.zshrc` and `~/.zprofile`
- `~/.ssh/config`
- `~/.config/1Password/ssh/agent.toml`
- `~/Library/Application Support/Code/User/settings.json`

Configured copies use backups where the tasks specify them. Review both the
task and source file before editing or running those sections. Do not add
private keys, tokens, passwords, or machine-local secrets to this project.

The defaults task includes power settings and the hard-coded computer names in
`tasks/macos_defaults.yml`; some changes require logout or reboot. The Dock task
is destructive to the current layout. Obtain explicit approval immediately
before a live application of those changes.

## Manual follow-up

- Restore private SSH and GPG keys outside the playbook.
- Sign into 1Password before relying on its SSH agent.
- Activate licensed applications such as Parallels Desktop and CrossOver.
- Install applications absent from the current Homebrew cask and MAS lists.

## Validation

```bash
cd mac
ansible-lint main.yml
ansible-playbook main.yml --syntax-check
```

These are local structural checks. Only an authorized live run plus checks of
the affected files, packages, services, defaults, and UI can verify runtime
state.
