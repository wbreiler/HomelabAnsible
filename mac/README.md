# MacAnsible

Ansible playbook to provision my Mac from a fresh install. Covers everything: Homebrew packages, Mac App Store apps, dotfiles, macOS system preferences, Dock layout, and homelab `/etc/hosts` entries.

## Prerequisites

On a brand-new Mac, do these three things before running the playbook:

```bash
# 1. Install Xcode Command Line Tools (GUI dialog — click Install)
xcode-select --install

# 2. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 3. Install Ansible
brew install ansible
```

Also make sure you're **signed into the App Store** before running — the MAS tasks require it.

## Usage

```bash
# Clone the repo
git clone git@github.com:wbreiler/MacAnsible.git ~/Developer/MacAnsible
cd ~/Developer/MacAnsible

# Install the required Ansible collection
make install

# Run the full playbook (will prompt for sudo password)
make run
```

### Running specific sections

```bash
make run-tags TAGS=homebrew          # just Homebrew packages
make run-tags TAGS=defaults,dock     # system preferences + Dock
make run-tags TAGS=shell             # Oh My Zsh + dotfiles
make check                           # dry run — no changes applied
```

Available tags: `xcode`, `homebrew`, `mas`, `shell`, `git`, `ssh`, `vscode`, `hosts`, `dock`, `defaults`

## What's Included

| Section | Details |
|---------|---------|
| **Homebrew** | 22 taps, 100+ formulae, 60+ casks |
| **App Store** | 20 apps — Logic Pro, Final Cut Pro, Pixelmator Pro, Infuse, Keynote/Numbers/Pages, and more |
| **Shell** | Oh My Zsh (theme: `apple`), plugins, aliases, pyenv, `.zshrc`, `.zprofile` |
| **Git** | Global config with GPG commit signing |
| **SSH** | `~/.ssh/config` with OrbStack integration and 1Password SSH agent |
| **VS Code** | 30+ extensions and full `settings.json` |
| **Hosts** | Homelab server entries in `/etc/hosts` |
| **Dock** | App layout (Firefox, Messages, Discord, Music, iTerm, Claude) + Downloads folder |
| **macOS defaults** | Dark mode, Finder, trackpad, screenshots to iCloud, power management, hostname |

## After Running

A few things still need to be done manually:

- **GPG key** — `gpg --import your-key.asc`
- **SSH keys** — restore private keys from 1Password or backup (e.g. `~/.ssh/PiKeys`)
- **LM Studio** — download from [lmstudio.ai](https://lmstudio.ai) (no Homebrew cask)
- **Parallels Desktop** — activate license after install
- **CrossOver** — activate license after install
