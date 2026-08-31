# First setup guide

Use this guide for the first Ansible-managed setup of the Windows gaming PC.
The role does not install Windows, partition disks, create the interactive
Windows user, or configure dual booting. Start after Windows is installed and
the intended desktop user can sign in normally.

Run every Ansible command from the `desktop/` directory so the local inventory,
role path, and Ansible configuration are used.

## What you need

- The gaming PC connected to the trusted home network
- Windows Pro with an administrator able to run PowerShell as Administrator
- The PC's hostname and IP address
- Ansible on the controller, including Python WinRM support
- The password you want to assign to the dedicated local `ansible` account
- Credentials for `\\10.10.20.3\clips`
- The Ansible Vault password you want to use for this project

The Windows Hello PIN for the normal desktop user cannot authenticate a remote
WinRM session. The bootstrap creates a separate local administrator named
`ansible`; do not reuse the interactive user's Microsoft account password.

## 1. Review what the role will change

Before connecting to the PC, review:

```bash
cd desktop
less group_vars/gaming_pc/main.yml
less roles/gaming_pc/tasks/main.yml
```

Pay particular attention to:

- `gaming_pc_winget_packages`
- `gaming_pc_install_approved_applications`
- Windows and driver update controls
- `gaming_pc_reboot_after_updates`
- The SMB path, username, and drive letter

The application approval flag also gates WinGet setup, WSL installation, and
Windows optional features. Windows updates, driver updates, and the SMB mapping
have separate controls. A live run can reboot Windows when an enabled feature
or update requires it.

## 2. Bootstrap Windows once

Copy `desktop/bootstrap-winrm.ps1` to the Windows PC. Open PowerShell **as
Administrator**, change to the directory containing the script, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\bootstrap-winrm.ps1
```

When prompted, enter a strong password for the new local `ansible` account and
retain it for the encrypted vault. The script:

- creates or repairs the local `ansible` account;
- adds it to the local Administrators group;
- enables and starts WinRM configuration; and
- permits the local administrator to receive an elevated remote token.

It does not store the password. Record the exact computer-qualified username
printed at the end, such as `KRATOS\ansible`.

## 3. Create the local inventory and encrypted vault

On the Ansible controller:

```bash
cd desktop
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.yml.example inventory/hosts.yml
cp group_vars/gaming_pc/vault.yml.example \
  group_vars/gaming_pc/vault.yml
```

Edit `inventory/hosts.yml` and set:

- `ansible_host` to the PC's current IP address; and
- `ansible_user` to the exact name reported by the bootstrap.

Edit `group_vars/gaming_pc/vault.yml` and replace both placeholders:

```yaml
gaming_pc_ansible_password: the-local-ansible-account-password
gaming_pc_smb_password: the-clips-share-password
```

Encrypt the file immediately:

```bash
ansible-vault encrypt group_vars/gaming_pc/vault.yml
```

Both local files are ignored by Git. Confirm that before continuing:

```bash
git status --short
```

Neither `inventory/hosts.yml` nor `group_vars/gaming_pc/vault.yml` should be
listed.

## 4. Test the connection without changing Windows

On macOS, use a writable local temporary directory and disable Apple's unsafe
post-fork Objective-C initialization check for Ansible's worker processes:

```bash
mkdir -p /tmp/desktop-ansible-local
ANSIBLE_LOCAL_TEMP=/tmp/desktop-ansible-local \
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
ansible gaming_pc -m ansible.windows.win_ping --ask-vault-pass
```

Expected result:

```text
gaming-pc | SUCCESS => {
    "ping": "pong"
}
```

If Python reports that WinRM is unavailable, install the `pywinrm` package in
the same Python environment used by Ansible, then repeat the connection test.
Do not continue to the playbook until `win_ping` succeeds.

## 5. Preview the first run

Check mode is the approval boundary. It can identify intended changes, but some
Windows and WinGet operations cannot perfectly predict their live result.

```bash
ANSIBLE_LOCAL_TEMP=/tmp/desktop-ansible-local \
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
ansible-playbook site.yml --ask-vault-pass --check --diff
```

Review the complete result. In particular, confirm that the package list, SMB
path, drive letter, optional features, update categories, and possible reboot
behavior still match your intent.

## 6. Apply the role

Save work on the PC and close games before the first live run. The role may
install applications and Windows updates and may reboot the machine.

```bash
ANSIBLE_LOCAL_TEMP=/tmp/desktop-ansible-local \
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
ansible-playbook site.yml --ask-vault-pass
```

Do not interrupt the run merely because WinRM temporarily disconnects during an
Ansible-managed reboot. Wait for the play recap and require `failed=0` before
considering the application successful.

## 7. Finish the interactive-user setup

Sign in as the normal desktop user after the playbook completes. Install or
verify the packages listed under `gaming_pc_interactive_user_packages` in
`group_vars/gaming_pc/main.yml`. Those packages intentionally are not installed
through WinRM because doing so would attach user-scoped applications to the
local `ansible` account.

Finally, verify:

- Windows Update has no unexpected pending restart;
- `Z:` opens `\\10.10.20.3\clips` for the interactive user;
- Steam and the approved machine-wide applications launch;
- WSL opens if it remains in the approved package list; and
- Device Manager shows the expected hardware without warning icons.

Re-run the playbook after later desired-state edits, beginning with the check
mode command in step 5. Treat every application-list change as a new review and
approval decision.
