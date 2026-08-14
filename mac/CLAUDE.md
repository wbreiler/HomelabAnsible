# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
make install          # Install community.general Ansible collection (run once)
make run              # Run full playbook (prompts for sudo password)
make run-tags TAGS=homebrew          # Run specific tag(s) only
make run-tags TAGS=defaults,dock     # Multiple tags
make check            # Dry-run (--check mode, no changes applied)
ansible-lint main.yml # Lint the playbook (warnings expected, no failures)
```

## Architecture

The playbook runs entirely on `localhost` (`connection: local`, no inventory file needed). `main.yml` is the entry point — it imports task files from `tasks/` with matching tags so individual sections can be run independently.

### Task files and their tags

| File | Tag | Notes |
|------|-----|-------|
| `tasks/xcode_clt.yml` | `xcode` | Uses `softwareupdate` to install CLT non-interactively |
| `tasks/homebrew.yml` | `homebrew` | Taps → formulae → casks in that order; uses `ignore_errors: true` for custom-tap packages that may move |
| `tasks/mas.yml` | `mas` | Requires App Store sign-in; large apps (Logic Pro, FCP) only install if previously purchased |
| `tasks/shell.yml` | `shell` | Installs Oh My Zsh unattended, copies `files/zshrc` and `files/zprofile`; zsh-syntax-highlighting sourced directly from Homebrew in zshrc |
| `tasks/git.yml` | `git` | Sets global git config including GPG signing key |
| `tasks/ssh.yml` | `ssh` | Copies `files/ssh_config`; private keys are NOT managed here |
| `tasks/vscode.yml` | `vscode` | Copies `files/vscode_settings.json`, installs extensions via `code --install-extension` |
| `tasks/hosts.yml` | `hosts` | Adds homelab IPs via `blockinfile`; requires `become: true` |
| `tasks/dock.yml` | `dock` | Uses `dockutil` (installed via Homebrew) + `osx_defaults` |
| `tasks/macos_defaults.yml` | `defaults,macos` | Applies `defaults write` for system prefs; restarts Finder/SystemUIServer at end |

### Static files

`files/` holds dotfiles and config that are copied verbatim:
- `zshrc` / `zprofile` — shell config with Oh My Zsh, pyenv, aliases
- `ssh_config` — includes OrbStack config at top (required to be first), 1Password agent for all hosts
- `vscode_settings.json` — full VS Code settings

### Dependencies

- `community.general` collection provides: `homebrew`, `homebrew_tap`, `homebrew_cask`, `mas`, `osx_defaults`, `git_config`
- `dockutil` is installed by `tasks/homebrew.yml` before `tasks/dock.yml` runs

### What is NOT automated

- Private SSH keys (restore from 1Password or backup)
- GPG private key import (`gpg --import`)
- LM Studio (no Homebrew cask)
- License activation for Parallels Desktop and CrossOver
