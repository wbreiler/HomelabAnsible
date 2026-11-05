# Observer deployment

The independent `homelab-offsite-observer` repository owns the application,
installer, configuration schema, systemd sandbox, and activation checks.
Use its `docs/DEPLOYMENT.md` for credentials and provider acceptance.
The installer leaves monitoring disabled. A guest on the home cluster cannot
provide an independent offsite view of a home power or Internet outage.

## Provisioning

Terraform owns the dedicated unprivileged Debian LXC and its firewall.
Copy [the template](../../terraform/proxmox/offsite-observer.tf.example) to
an ignored `offsite-observer.local.tf` in `terraform/proxmox/`.
Verify the VMID against live guests and retained installation inputs. Check
the static address against live configuration, reservations, and DHCP ranges.
Use the existing scoped Terraform ACL workflow and saved-plan review.

The template uses one CPU, 512 MiB memory, and an 8 GiB local disk. It omits
nesting, host mounts, devices, and guest SSH credentials. Create the guest
stopped with its firewall, then review a second plan that only starts it.
The firewall drops inbound connections and permits outbound DNS to the two
configured public resolvers plus TCP 80/443. It does not restrict HTTP/HTTPS
destinations. Confirm cluster firewall enforcement before relying on it.
Optional private checks require a separately reviewed network policy.

Do not use `deploy_guest.py` for this service: its application allowlist,
SSH handoff, memory minimum, and nesting bootstrap serve different guests.
Do not add an Ansible provisioning or lifecycle owner.

## Install through the Proxmox console

Export a clean, reviewed application commit with `git archive`. Record the
commit and archive SHA256 in the private deployment evidence. Transfer the
archive through the trusted Proxmox host, verify its SHA256, and use `pct push`
to place it in the new guest. Extract it into `/root/offsite-observer-source`.
Never include the controller working tree, private inputs, or Git credentials.

From the guest console, or `pct exec VMID -- bash` on its current node:

```sh
apt-get update
apt-get install --no-install-recommends python3 ansible-core ca-certificates dbus systemd
cd /root/offsite-observer-source
ANSIBLE_CONFIG=deploy/ansible.cfg ansible-playbook -i deploy/inventory.local.yml deploy/install.yml --check --diff
ANSIBLE_CONFIG=deploy/ansible.cfg ansible-playbook -i deploy/inventory.local.yml deploy/install.yml
```

Disable template SSH units and other unused listeners after installation.
Keep console access. Verify `ss -lntup`, the unprivileged UID map, synchronized
host/guest time, unit syntax, timer state, root-only configuration, and a repeat
installer run. Missing credential preflight failures are expected before setup.
Use an inert configuration for any sandbox smoke test. Never substitute fake
credentials into production credential paths or enable the timer to test installation.

### Guest mount checks

Check `dev-mqueue.mount`, `run-lock.mount`, and `tmp.mount` after installation.
On the unprivileged observer, the kernel audit log identified AppArmor denials
for the move operation at those three destinations. On empty disposable paths
in the guest, tmpfs and mqueue both succeeded with the classic mount operation.

For that confirmed failure, each affected unit uses a guest-local drop-in at
`/etc/systemd/system/<unit>.d/50-lxc-classic-mount.conf`:

```ini
[Mount]
Environment=LIBMOUNT_FORCE_MOUNT2=always
```

Before starting a mount, check for files, open handles, and private service
directories beneath its destination. Preserve any data and directory permissions.
Reload systemd, start each affected unit and verify its filesystem and options
with `findmnt --mountpoint`. Test an unprivileged temporary-file write, a lock
under `/run/lock`, and a POSIX queue send/receive. This setting is limited to
the three mount helpers. See the [util-linux mount documentation](https://github.com/util-linux/util-linux/blob/master/sys-utils/mount.8.adoc#environment).

If a wtmpdb upgrade retires `wtmpdb-rotate.timer`, check the installed package
changelog, the active `logrotate.timer`, and `logrotate --debug /etc/logrotate.conf`.
If its old activation link is dangling, save that link for rollback, remove it
from `timers.target.wants`, reload systemd, and clear that timer's failed state.

## Add private inputs later

Inside the guest, create a mode-0700 `/root/offsite-private` directory. Copy
`config.telegram.example.json` and `deploy/inputs.example.yml` there as
`config.json` and `inputs.yml`. Keep configuration and token files mode 0600.
Set the real targets and exact response contracts. Keep `enabled` and
`provider.contract_verified` false during setup.

Supply the dedicated Telegram bot token, chat ID, and Healthchecks check UUID
as the separate files named in `inputs.yml`. Do not paste secrets into argv,
repository files, or this documentation. Then run from the source directory:

```sh
ANSIBLE_CONFIG=deploy/ansible.cfg ansible-playbook -i deploy/inventory.local.yml deploy/install.yml -e @/root/offsite-private/inputs.yml
```

Follow the application's deployment guide for the home freshness endpoint,
real notification receipt, missing-heartbeat drill, and explicit activation.
Installing credentials alone does not activate monitoring. Leave optional
Tailscale/private coverage disabled until its endpoint and grant exist.

## Backups and evidence

Verify the existing all-guest PBS job includes this VMID. Preserve
`/etc/offsite-observer`, `/var/lib/offsite-observer`, units, and source identity.
Confirm encryption and perform an isolated restore before claiming recovery
readiness. Keep the restored guest disconnected and its timer disabled.

Store real deployment identity, source hash, Terraform plans/state, installation
logs, and validation evidence under ignored
`terraform/proxmox/artifacts/offsite-observer/`. Do not commit these artifacts.
An installed, disabled guest is not evidence of provider delivery or monitoring.
