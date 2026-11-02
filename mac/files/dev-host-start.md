# Development workspace

Save project files in this host's `~/Developer` directory. Files remain on the
host when a client disconnects. The bootstrap does not migrate repositories,
credentials, or application history automatically.

Connect through the SSH alias configured for this host. In Zed, select
**File > Open Remote**, enter that alias, and open the remote `~/Developer`.
The editor runs locally. Files, terminals, and builds run on the remote Mac.
Authenticate with your existing SSH agent. Do not copy private keys or
account tokens into this directory.

Use `tmux new -As dev` for a terminal session that survives a disconnected
client. Detach with Ctrl-B, then D. Reconnect with the same command.

Available bootstrap tools include Node/npm, Python 3.13/uv, Git/Git LFS,
GitHub CLI, Ansible, CMake, Ninja, and Apple's Command Line Tools.
Run `dev-host-check` to verify Git commits, JavaScript, Python, and C/CMake
builds. Use a project virtual environment (`uv venv`) instead of system-wide
pip installations. Global npm packages install under `~/.local` without sudo.

GitHub CLI and other account-based tools require your own sign-in. This
bootstrap targets Intel x86_64. Review ARM-only dependencies and build flags
before building a migrated project. Container runtimes and full Xcode are
not installed by the minimal bootstrap.

Verify backup coverage separately. The bootstrap does not create a PBS job.
Before deleting source files, verify local branches, untracked/ignored files,
and a recoverable backup. Unsaved editor buffers are not protected.

The former Atlas VM 108 and its hourly backup job were retired on 2026-10-29.
Do not reuse its old address or `atlas-dev` alias without checking the target.
Historical migration and restore results are in `mac/DEV-HOST.md` and
`proxmox/docs/macos-follow-up.md` within HomelabAnsible.

The optional desktop host needs its own sign-in, pairing, and graphical login
before remote desktop work. Application history and active chats do not
synchronize through a one-time repository copy. See `mac/DEV-HOST.md` for
historical setup notes and the separate full development role.
