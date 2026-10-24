# Atlas development workspace

This directory is on the development VM. Laptop projects were copied on
2026-10-24. The laptop originals remain intact.
Save future project files here so they stay on the VM when a client disconnects.

Connect from a configured client with `ssh atlas-dev`.
In Zed, select **File > Open Remote**, connect to `atlas-dev`, and open
`/Users/pve/Developer`. The editor runs locally. Files, terminals, and builds
run on the VM. Authenticate with your existing SSH agent. Do not copy private
keys or laptop account tokens into this directory.

Use `tmux new -As dev` for a terminal session that survives a disconnected
client. Detach with Ctrl-B, then D. Reconnect with the same command.

Available tools include Node/npm, Python 3.13/uv, Git/Git LFS, GitHub CLI,
Ansible, CMake, Ninja, and Apple's Command Line Tools. Run `dev-host-check`
to verify Git commits, JavaScript, Python, and C/CMake builds. Use a project
virtual environment (`uv venv`) instead of system-wide pip installations.
Global npm packages install under `~/.local` without sudo.

The APFS filesystem now uses the 512 GiB disk. The migration preserved Git
history, branches, stashes, and uncommitted work. Rebuildable caches and
Finder metadata were excluded. These credential files remain on the laptop:

- `ProxmoxMCP/proxmox.json`
- `HomelabAnsible/proxmox/files/gallery-dl-cookies.txt`
- `docker-wyze-bridge/app/.env`

The Wyze file is tracked, so its absence appears as a deletion in Git status.
Do not commit that deletion. Recreate its configuration when needed.

The VM has its own local user account. GitHub CLI and other account-based
tools still require your sign-in. The VM is Intel x86_64. ARM-only project
dependencies and build flags need separate review. Mineways has a tested Intel
build at `~/Builds/Mineways-intel` and an application at
`~/Applications/Mineways.app`. This build copy is separate from your source.
Its port regression tests passed. GUI interaction remains untested.

The dedicated Proxmox job backs up this VM to PBS hourly at :15.
The existing all-guests job also runs every six hours at :30 and handles retention.
This includes uncommitted files saved on the VM. A missed job or a failed job
can leave an older recovery point. Unsaved editor buffers are not protected.
The PBS copy is on another homelab machine. It is not an offsite backup.
Before deleting any laptop originals, verify the copy, local Git branches,
untracked and ignored files, and a recoverable backup of the migrated data.

## Codex remote host

Open `~/Applications/ChatGPT.app` in this VM and sign in to your ChatGPT
account. This app includes Codex. Under **Settings > Connections > Control
this Mac**, enable remote access and pair your phone. On your laptop, use
**Control other devices** to pair with this VM. Use the same account and
workspace on all devices. Add the repositories in this directory as projects.

The app opens after a graphical macOS login. After a VM restart, sign into
macOS to make the desktop host available. Keep the app running. Your laptop
can then disconnect while the VM remains the independent host.

The laptop and phone were paired on 2026-10-24. The imported Codex history
contains 496 chats. The laptop originals remain available as a fallback.
Old chats can reference deleted workspaces or laptop file paths. The active
conversation was copied as a snapshot. New messages do not synchronize through
this one-time import.
