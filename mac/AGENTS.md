# AGENTS.md

Guidance for AI agents working in the macOS provisioning project. Treat the
playbook and task files as the source of truth when prose documentation has
drifted.

## Scope and entry point

- Run commands from `mac/`; this project has no inventory file.
- `main.yml` runs only against `localhost` with `connection: local` and imports
  the task files in `tasks/`.
- This playbook is Apple-silicon-specific: its Homebrew prefix and executable
  paths are `/opt/homebrew`. Preserve native arm64 paths and packages unless a
  requested change explicitly broadens platform support.
- Several tasks overwrite user configuration files with the tracked files in
  `files/`, using Ansible backups where configured. Review both the task and
  source file before changing such behavior.

## Common commands

```bash
make install                       # Install requirements.yml collections
make run                           # Apply the full playbook; prompts for sudo
make run-tags TAGS=homebrew        # Apply one tag
make run-tags TAGS=defaults,dock   # Apply multiple tags
make check                         # Full check-mode run; prompts for sudo
ansible-lint main.yml              # Lint from this directory
ansible-playbook main.yml --syntax-check
```

Check mode is not runtime verification. Some command, shell, Homebrew, MAS,
Dock, and macOS-defaults operations may be incomplete or noisy in check mode;
do not claim convergence without an authorized live run and relevant
post-change checks.

## Task map

| File | Tag(s) | Current behavior |
| --- | --- | --- |
| `tasks/xcode_clt.yml` | `xcode` | Detects and, when absent, installs Xcode Command Line Tools with `softwareupdate`. |
| `tasks/homebrew.yml` | `homebrew` | Installs Homebrew if needed, then taps, formulae, casks, Dock prerequisites, and sudo-touchid setup. Formula and cask loops tolerate failures. |
| `tasks/mas.yml` | `mas` | Installs App Store apps as root with `mas`; the user must already be signed in and some apps depend on account entitlement. |
| `tasks/shell.yml` | `shell` | Installs Oh My Zsh, deploys `zshrc`/`zprofile`, manages pyenv Python and selected global pip/npm packages, and sets zsh as the login shell. |
| `tasks/git.yml` | `git` | Sets the global Git name/email and installs Git LFS hooks; commit signing is not configured. |
| `tasks/ssh.yml` | `ssh` | Deploys SSH and 1Password SSH-agent configuration; it does not manage private keys. |
| `tasks/vscode.yml` | `vscode` | Deploys VS Code settings and installs extensions through `code`. |
| `tasks/hosts.yml` | `hosts` | Replaces the Ansible-managed block in `/etc/hosts`; requires privilege escalation. |
| `tasks/dock.yml` | `dock` | Destructively replaces the user's Dock layout, then restarts Dock. |
| `tasks/macos_defaults.yml` | `defaults`, `macos` | Applies user and privileged defaults, power settings, and host naming, then restarts Finder and SystemUIServer. Some settings require logout or reboot. |

## Managed static files

Files under `files/` are copied into the user's home directory:

- `zshrc` and `zprofile` provide the shell environment, aliases, Homebrew and
  pyenv setup.
- `ssh_config` contains homelab host/network rules and 1Password agent wiring.
- `1password-agent.toml` configures the 1Password SSH agent.
- `vscode_settings.json` is the complete managed VS Code settings file.

Do not add private keys, tokens, passwords, or machine-local secrets. Private
SSH keys must remain outside this project.

## Dependencies and ordering

- `requirements.yml` installs `community.general`, which supplies the Homebrew,
  MAS, macOS defaults, and Git configuration modules.
- Homebrew installs `dockutil` before the Dock tasks use it during a full run.
- App Store tasks need an authenticated App Store session.
- VS Code extension tasks need the `code` launcher available on `PATH`.
- sudo-touchid bootstrap writes `/etc/pam.d/sudo_local` under `become`, but its
  Homebrew login service must start as the normal user. Never run `brew services
  start sudo-touchid` as root; doing so can damage Homebrew path ownership.

## Safety and validation

- Inspect the exact tagged task before a live run. `homebrew`, `mas`, `shell`,
  `git`, `ssh`, and `vscode` mutate the user's environment; `hosts`, `dock`, and
  `defaults` also affect system or visible session state.
- Obtain explicit user approval immediately before applying changes. Syntax,
  lint, and check-mode commands do not authorize a live playbook run.
- In particular, `dock` removes every existing Dock item before rebuilding it,
  and `defaults` changes power/hostname settings and restarts UI processes.
- Preserve the distinction between root-only setup and user-level Homebrew
  services. Do not run Homebrew itself under `sudo`.
- Validate YAML syntax and lint after changes. For a live tagged run, verify the
  affected files, defaults, services, applications, or UI state afterward.

## Manual responsibilities

The playbook does not restore private SSH or GPG keys and does not perform
license activation. Applications absent from the Homebrew cask and MAS lists
remain manual installs.
