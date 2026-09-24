# FastChannels on erebus

The scoped playbook deploys [FastChannels v5.3.2](https://github.com/kineticman/FastChannels/releases/tag/v5.3.2)
as a TrueNAS custom app on `10.10.20.3:5523`. It creates dedicated bind-mount
directories at `/mnt/gaia/appdata/fastchannels/data` for the database and
`/mnt/gaia/appdata/fastchannels/android` for ADB keys. These paths are outside
TrueNAS's internal Docker app storage.

From `truenas/`, after the configuration backup:

```sh
ansible-playbook playbooks/fastchannels.yml --check --diff
ansible-playbook playbooks/fastchannels.yml -e truenas_allow_changes=true
ansible-playbook playbooks/fastchannels.yml -e truenas_allow_changes=true
```

Open `http://10.10.20.3:5523/admin/`. The admin page is on the LAN address;
the application does not provide a login gate. Configure sources and feeds in
the web interface. Initial scrapes can take several minutes.
