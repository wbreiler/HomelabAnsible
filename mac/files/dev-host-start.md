# Atlas development workspace

This directory is on the development VM. Laptop projects have not been copied.
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

The VM has its own local user account. GitHub CLI and other account-based
tools still require your sign-in. The VM is Intel x86_64. ARM-only project
dependencies and build flags need separate review.

The dedicated Proxmox job backs up this VM to PBS hourly at :15.
The existing all-guests job also runs every six hours at :30 and handles retention.
This includes uncommitted files saved on the VM. A missed job or a failed job
can leave an older recovery point. Unsaved editor buffers are not protected.
The PBS copy is on another homelab machine. It is not an offsite backup.
Before deleting any laptop originals, verify the copy, local Git branches,
untracked and ignored files, and a recoverable backup of the migrated data.
