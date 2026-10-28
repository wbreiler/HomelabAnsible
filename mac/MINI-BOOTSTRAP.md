# Bootstrap a dedicated Mac Mini

Start with a monitor, keyboard, and wired Ethernet connected to the Mini.
Allow 1–2 hours, mostly for downloads. Keep physical access for recovery tests.
This procedure targets an Apple silicon Mini and the normal development account.

The dev role installs public SSH keys and the homelab SSH configuration. It
never copies private keys, passwords, or authenticated sessions. The hosts task
maps Erebus to `10.10.10.7`. No hosts-task exclusion is required.

## 1. Prepare fresh macOS — on the Mini

1. Complete Setup Assistant with an administrator account named `wbreiler`.
2. Install available macOS updates.
3. Reserve the Mini's Ethernet IP address in your router.
4. Enable FileVault and store its recovery key in 1Password.
5. Grant Terminal access under **System Settings > Privacy & Security > Full Disk Access**.

Quit and reopen Terminal after granting access. Keep automatic login disabled.
An Apple Account or App Store sign-in is optional for the dev role.
If you use another account name, replace `wbreiler` in the SSH alias below.
The playbook uses the current account's home directory.

## 2. Transfer the committed repository — on the controlling Mac

The latest work can remain unpushed. Create a Git bundle from your local `main`
branch. The bundle contains committed files and history, including the public
keys. It excludes ignored inventories and other untracked files.

```bash
cd /Users/wbreiler/Developer/HomelabAnsible
git log -1 --oneline
git bundle create /tmp/HomelabAnsible.bundle main
open -R /tmp/HomelabAnsible.bundle
```

Record the displayed commit ID. AirDrop the bundle to the Mini and place it in
its Downloads folder. Compare the commit ID after cloning below. A clone from
GitHub alone will not include commits that you have not pushed.

## 3. Install bootstrap tools — on the Mini

Install Command Line Tools:

```bash
xcode-select --install
```

**Wait for the installer to finish before continuing.**
Install Homebrew with its [official installer](https://brew.sh/):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Load Homebrew into this terminal and install Ansible:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install ansible ansible-lint
```

Clone the transferred bundle and configure the normal GitHub remote:

```bash
mkdir -p "$HOME/Developer"
git clone --branch main \
  "$HOME/Downloads/HomelabAnsible.bundle" \
  "$HOME/Developer/HomelabAnsible"
git -C "$HOME/Developer/HomelabAnsible" remote set-url origin \
  git@github.com:wbreiler/HomelabAnsible.git
git -C "$HOME/Developer/HomelabAnsible" log -1 --oneline
```

Confirm that the commit ID matches the controlling Mac. No GitHub authentication
is needed to clone the local bundle. Changing the remote does not push anything.

## 4. Apply the complete dev role — on the Mini

Install collections, validate the source, and apply the role:

```bash
cd "$HOME/Developer/HomelabAnsible/mac"
make install
make validate
make run-dev REMOTE_ACCESS=true
```

Run these commands as the normal account. Enter the Mini's administrator
password when Ansible requests it. Do not run Homebrew or the entire playbook
under sudo. `make run-dev REMOTE_ACCESS=true` includes the hosts task and the corrected Erebus entry.

Require `failed=0` in the play recap. Review any ignored failures before
continuing. If installation fails, resolve the reported cause and rerun
`make run-dev REMOTE_ACCESS=true` from the same directory.

Open a fresh login shell after installation:

```bash
exec /bin/zsh -l
```

Check the managed hostname entry:

```bash
dscacheutil -q host -a name erebus
```

The result should include `ip_address: 10.10.10.7`. Deluge uses the separate
TrueNAS app address `10.10.20.3`. The [hosts audit](HOSTS-AUDIT.md) records the
remaining entries and retirement evidence. All five obsolete legacy aliases
were removed, including Gallery and Cobbleverse after user confirmation.

## 5. Confirm macOS remote access — on the Mini

Open **System Settings > General > Sharing**:

1. Disable Remote Management if enabled.
2. Enable Screen Sharing.
3. Restrict Screen Sharing to the development account.
4. Enable Remote Login.
5. Confirm that Remote Login permits the development account.

The role configures these services. Verify actual Screen Sharing control from
another Mac before unattended use. A loaded service does not establish control.
See Apple's [Screen Sharing instructions](https://support.apple.com/guide/mac-help/turn-screen-sharing-on-or-off-mh11848/mac).

## 6. Complete manual sign-ins — on the Mini

1. Open 1Password, sign in, and unlock the vault.
2. Enable **Settings > Developer > Use the SSH agent** in 1Password.
3. Open ChatGPT and sign into the intended account and workspace.
4. Pair devices through **Settings > Connections > Control this Mac or PC**.
5. Sign into the Codex CLI with the commands below.

```bash
codex login
codex login status
```

Complete account verification and macOS permission prompts. The login agent
opens the ChatGPT desktop host after graphical login. It does not create the
session, authenticate accounts, or pair devices automatically.

Use the Homebrew-installed 1Password desktop app. Its agent socket matches the
managed configuration. Follow the [1Password SSH agent instructions](https://developer.1password.com/docs/ssh/get-started/)
for its authorization settings.

Check the agent and GitHub authentication:

```bash
ssh-add -l
ssh -T git@github.com
```

Approve 1Password's key-use prompt. GitHub's success message states that you
authenticated but that GitHub provides no shell access. Exit status `1` is
normal for that successful test.

The role installs six public key selectors. Only the cluster key grants
incoming SSH access by default. Existing authorized keys remain. The matching
private keys must remain in 1Password or another approved credential agent.
A forwarded agent is temporary and cannot support independent work after its
connection ends. Unlock the local agent after login for outbound operations.

## 7. Verify access — from the controlling Mac

First, display the Mini's host-key fingerprint **on the Mini**:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

On the **controlling Mac**, unlock 1Password and enable its SSH agent. Add this
entry to `~/.ssh/config`. Replace `<reserved-mini-IP>` with the router reservation:

```sshconfig
Host mac-mini-dev
  HostName <reserved-mini-IP>
  User wbreiler
  IdentityFile ~/.ssh/cluster.pub
  IdentitiesOnly yes
```

Connect from the controlling Mac:

```bash
ssh mac-mini-dev
```

Compare the offered fingerprint with the Mini's fingerprint before accepting
it. Approve any controller-side 1Password prompt. Exit the session afterward:

```bash
exit
```

Run the authentication and CLI checks from the controlling Mac:

```bash
ssh -o BatchMode=yes mac-mini-dev true
ssh mac-mini-dev \
  '/bin/zsh -lc "command -v codex && codex login status"'
```

The first command should finish without a password prompt. The second should
find Codex and report authenticated status. The explicit login shell loads the
Homebrew PATH for the remote command.

Complete the graphical and local checks:

1. Open Screen Sharing on the controlling Mac.
2. Connect to the Mini's reserved IP address.
3. Log into the development account and verify keyboard and mouse control.
4. Verify Remote Control from a paired device.
5. Run the readiness check on the Mini.

```bash
~/Developer/mac-dev-check.sh
```

For SSH-based Codex projects, add `mac-mini-dev` under **Settings > Connections**
on the controlling desktop app. Follow the [official SSH host instructions](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host).

Use the LAN or a VPN on another device/router for recovery access. Do not depend
on a VPN process running on the Mini to reach its preboot environment. The role
does not create public router forwards or expose an app-server listener.

## 8. Test a planned restart

**Save work first. A restart stops active tasks. Keep physical access available
for this first test.**

1. Restart the Mini through the Apple menu.
2. Connect from the controlling Mac with `ssh mac-mini-dev`.
3. Complete any FileVault authentication prompt.
4. Connect through Screen Sharing and log into the desktop.
5. Unlock 1Password and repeat the readiness checks below.

Apple supports [SSH FileVault unlock](https://support.apple.com/guide/security/managing-filevault-sec8447f5049/web)
after restart on Apple silicon with macOS 26 or later, when networking is
available. Verify this behavior on the installed macOS version. Normal public
key authentication does not establish that preboot unlock works.

On the Mini:

```bash
codex login status
~/Developer/mac-dev-check.sh
```

Confirm that the desktop app opened automatically and that a paired device
reconnects. Existing authentication should persist. Complete any new sign-in
prompt. If preboot SSH presents a different host key, verify it physically.
Do not bypass host-key checking. Use local FileVault unlock if remote unlock
is unavailable.

## 9. Test cold boot separately

**Shut down normally. Do not pull power from a running Mini.**

1. Shut down the Mini through the Apple menu.
2. Start it with the power button.
3. Test SSH and FileVault unlock from the controlling Mac.
4. Use local unlock if remote unlock fails.
5. Repeat desktop login, 1Password unlock, and the readiness checks.

Desktop Remote Control requires graphical login. SSH-based Codex access can
work once macOS is unlocked without a graphical session on the Mini. It still
requires CLI authentication and the credentials needed by its projects.

The role enables restart after power loss, network wake, and AC sleep of zero.
These settings do not unlock FileVault, create a desktop session, or restore
interrupted tasks. Keep physical recovery available for real power failures.

See [MINI-RECOVERY.md](MINI-RECOVERY.md) if either access path fails. The role
copies both guides and the hosts audit to `~/Developer/` on the Mini. Hardware recovery remains
unverified until these checks pass on the actual Mini.
