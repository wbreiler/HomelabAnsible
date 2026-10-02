# Sonarr and Radarr NFS startup

Run `arr_storage.yml` from `proxmox/` against the guests directly. It reads
their existing IPv4 NFS entries in `/etc/fstab`; it does not change exports,
mount options, application paths, or network addresses.

Use an ignored inventory or a file outside the repository:

```yaml
arr_storage:
  hosts:
    sonarr:
      ansible_host: SONARR_IP
      arr_service: sonarr
    radarr:
      ansible_host: RADARR_IP
      arr_service: radarr
  vars:
    ansible_user: root
    ansible_python_interpreter: /usr/bin/python3
```

```sh
ansible-playbook -i /path/to/private-inventory.yml arr_storage.yml --check --diff
ansible-playbook -i /path/to/private-inventory.yml arr_storage.yml
```

The ifupdown `networking.service` must finish, including an IPv4 route check
for each NFS server, before `network-online.target`. Each application requires
all configured NFS mounts, including nested download mounts. Drop-ins survive
application service-template updates. No running service is restarted by the
playbook.

A systemd timer retries application activation each minute. Starting an
already active service does not restart it. For an intentional prolonged app
stop, stop its `APP-storage-retry.timer` first. The timer retries failed starts;
it does not detect a hung NFS server or provide storage redundancy.

After deployment, with explicit guest-reboot authorization, reboot one LXC at
a time. Confirm a changed guest boot ID, every fstab NFS target mounted, media
user access, HTTP `/ping`, and network → mounts → application ordering in the
boot journal. Check for failed units and ordering cycles. Repeat the playbook
to confirm `changed=0`. Host reboots are not part of this procedure.

Rollback: stop and disable the retry timer, restore backed-up overrides (or
remove the three files created by this playbook), then run
`systemctl daemon-reload`. The original fstab and application unit are intact.
