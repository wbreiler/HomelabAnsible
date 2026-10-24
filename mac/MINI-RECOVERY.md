# Dedicated Mac Mini: installation and recovery

The playbook prepares the Mini. Hardware recovery is **unverified** until the
checks below pass on that Mini. Keep physical access for the first tests.

## Before unattended use

1. Complete Setup Assistant with the normal administrator account.
2. Connect wired Ethernet and reserve the Mini's address in the router.
3. Install the dev role with `make run-dev` from `mac/`.
4. Enable Screen Sharing control for the development account in **General > Sharing**.
5. Complete the account setup below through Screen Sharing.

Grant the terminal Full Disk Access if `systemsetup` requests it. Disable
Remote Management before enabling Screen Sharing. Test actual keyboard and
mouse control from another Mac. A loaded launch service does not prove control.

Keep FileVault enabled. Store its recovery key in the password manager, outside
this repository. Confirm that the development account can unlock FileVault.
Keep macOS current before exposing remote services to the trusted network.

## Accounts and credentials

The role installs both `codex` (CLI) and `ChatGPT.app` (desktop host). Its login
agent opens the desktop host after graphical login. It does not enable automatic
macOS login, store account passwords, or pair devices automatically.

1. Sign into the desktop app with the intended account and workspace.
2. Pair devices in **Settings > Connections > Control this Mac or PC**.
3. Run `codex login` in the Mini's terminal.
4. Enable the Bitwarden SSH agent in the Bitwarden desktop app.
5. Unlock Bitwarden before outbound Git or homelab operations.

Approve any required macOS privacy prompts in the graphical session. The role
installs public key selectors for GitHub, Proxmox, TrueNAS, and other configured
hosts. The corresponding private keys must remain in the credential agent.
The role never copies or exports them.

The cluster public key grants incoming SSH access by default. Other existing
`authorized_keys` entries remain. The variable `mac_dev_authorized_key_files`
can select additional tracked public key filenames. Public selectors do not
provide private credentials or independently authenticate outbound connections.

A forwarded agent is a temporary alternative for trusted SSH sessions. It stops
being available when that connection ends. After a restart, desktop tasks need
the local credential agent unlocked again. This setup does not promise unattended
credential unlock or automatic continuation of an interrupted task.

## Verify both access paths before restart

Use the Mini's reserved address and its actual account name. This example is a
controller-side SSH alias. Replace both placeholders before using it:

```sshconfig
Host mac-mini-dev
  HostName <reserved-mini-address>
  User <development-account>
  IdentityFile ~/.ssh/cluster.pub
  IdentitiesOnly yes
```

Add this alias to the controlling Mac's `~/.ssh/config`, not the Mini's config.
The controlling Mac must have access to the cluster private key through its
agent. Verify the host-key fingerprint on the Mini before accepting it.

1. Run `ssh -o BatchMode=yes mac-mini-dev true` from the controlling Mac.
2. Run `ssh mac-mini-dev 'command -v codex && codex login status'`.
3. Connect to `vnc://<reserved-mini-address>` with Screen Sharing.
4. Run `~/Developer/mac-dev-check.sh` as the Mini's development user.
5. Verify Remote Control from a paired device.

For SSH-based Codex projects, add the alias in **Settings > Connections** on the
controlling desktop app. Codex starts its remote server through SSH. This path
can work without a graphical login on the Mini once the OS is unlocked. It
still requires CLI authentication and any credentials needed by its projects.
See the [official SSH host instructions](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host).

Keep access through the LAN or a VPN on another device/router. Do not depend on
a VPN process running on the Mini to reach its preboot environment. The role
does not install router forwards or expose an app-server listener.

## Planned restart and FileVault recovery

Apple supports [FileVault unlock through SSH](https://support.apple.com/guide/security/managing-filevault-sec8447f5049/web)
after restart on Apple silicon with macOS 26 or later, with Remote Login enabled
and network access available. Verify this on the installed macOS version.
Normal `authorized_keys` access does not establish that preboot unlock works.

**Save work before a restart. A restart stops active Codex tasks.** Perform the
first test while someone can reach the Mini physically.

1. Restart the Mini through the Apple menu.
2. Connect with `ssh mac-mini-dev` when the network becomes available.
3. Complete any FileVault authentication prompt.
4. Connect through Screen Sharing and log into the development desktop.
5. Unlock Bitwarden and repeat the access checks above.

If SSH reports a different host key during recovery, verify it at the Mini.
Do not disable host-key checking or delete the known key without verification.
If the documented SSH unlock is unavailable, unlock FileVault locally.

The login agent opens ChatGPT after desktop login. It does not create that
session. Remote Control remains unavailable until the desktop app is running
and authenticated. SSH-only Codex projects provide a separate recovery path.

## Cold boot and power failure

**Save work before shutdown. Do not pull power from a running Mini for this test.**
Cold boot requires a separate test from a planned restart. Apple describes SSH
FileVault unlock after restart. Do not assume every cold-boot case is equivalent.

1. Shut down the Mini normally while physical access is available.
2. Start it with its power button.
3. Test SSH and FileVault unlock from the controlling Mac.
4. Use local unlock if remote unlock is unavailable.
5. Repeat desktop login, credential unlock, and the access checks.

The role sets AC sleep to zero and enables network wake and restart after power
loss. A persistent marker protects this sleep policy from later main-role runs.
These settings do not unlock FileVault, create a desktop session, or restore
interrupted tasks. Keep a physical recovery path for real power failures.

## If the Mini is unreachable

Check its router lease and wired network first. Use normal SSH to separate an
app failure from an OS/network failure. If SSH works, use Screen Sharing to
restore the desktop session and inspect the app. In a graphical session,
`open -a /Applications/ChatGPT.app` opens the host app manually.

If the GUI login agent needs a retry, run this as the development user after
graphical login:

```bash
launchctl kickstart gui/$(id -u)/com.wbreiler.codex-desktop
```

If neither SSH nor Screen Sharing works, use the local console to inspect
FileVault, the network, and Sharing settings. Do not treat a local smoke check
as proof of remote reachability. Recheck access after macOS updates.
