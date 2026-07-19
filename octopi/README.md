# OctoPi Ansible Configuration

Configures an existing OctoPi image without replacing unrelated OctoPrint
settings. It manages:

- the default printer profile and serial connection defaults;
- an optional tagged Ethernet VLAN with DHCP through NetworkManager;
- an OctoPrint web user and password;
- pinned third-party plugins in OctoPrint's own virtual environment;
- arbitrary core and plugin settings through OctoPrint's supported config CLI;
- a controller-side G-code library, including nested directories;
- the OctoPrint systemd service.

It deliberately does **not** image Raspberry Pi OS, configure Wi-Fi, change the
SSH account, or upgrade OctoPrint itself.

## Setup

Run all commands from this directory so its `ansible.cfg` is used:

```bash
cd octopi
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
cp inventory.yml.example inventory.yml
cp group_vars/octopi_servers.yml.example group_vars/octopi_servers.yml
cp vault.yml.example vault.yml
```

Edit the three copied files. At minimum, set the OctoPi address, printer model
and dimensions, desired plugins/settings, web username, and web password.
Encrypt the secret:

```bash
ansible-vault encrypt vault.yml
```

Validate before applying:

```bash
ansible-lint
ansible-playbook site.yml --syntax-check --ask-vault-pass
ansible-playbook site.yml --check --diff --ask-vault-pass
```

Apply:

```bash
ansible-playbook site.yml --ask-vault-pass
```

The playbook restarts OctoPrint only when a user, plugin, or setting changes.
Plugin installation requires internet access from the OctoPi host.

## G-code library

Set an absolute controller-side path to copy all `.gcode` files into
OctoPrint's uploads directory. Nested directories are preserved, unrelated
remote files are not deleted, and non-G-code files such as `.DS_Store` are
excluded:

```yaml
octoprint_gcode_source: >-
  /Users/example/Library/Mobile Documents/com~apple~CloudDocs/3D Printing/G-Code/Printer
```

The source path is machine-specific and belongs in the ignored
`group_vars/octopi_servers.yml` file.

## Tagged Ethernet

Set `network_manage_vlan: true` to keep the physical Ethernet parent
unnumbered and obtain an address using DHCP on a tagged VLAN subinterface:

```yaml
network_manage_vlan: true
network_ethernet_interface: eth0
network_ethernet_parent_connection: Wired connection 1
network_vlan_id: 70
network_vlan_route_metric: 100
```

This requires NetworkManager and `community.general`. Configure the connected
switch port to carry the VLAN as tagged traffic before applying. Keep a
separate management path, such as Wi-Fi, available for the initial cutover.

## Plugins

Add pinned pip requirements to `octoprint_plugins`. OctoPrint's documentation
requires plugins to be installed with the Python environment that runs
OctoPrint, so the role uses `~/oprint/bin/pip`.

```yaml
octoprint_plugins:
  - name: Example plugin
    requirement: OctoPrint-Example==1.2.3
```

Use the package name and version published by the plugin maintainer. A tagged
archive URL or immutable Git commit is also accepted. Review a plugin before
installing it: plugins execute code with the OctoPrint service account.
Plugins that compile native extensions may also declare required Debian
packages:

```yaml
octoprint_plugin_system_packages:
  - python3-dev
```

## Plugin and core settings

Settings are additive and use dot-separated paths:

```yaml
octoprint_settings:
  - path: appearance.name
    value: Workshop Printer
  - path: plugins.example.enabled
    value: true
  - path: plugins.example.options
    value:
      retries: 3
```

The exact keys are plugin-specific. Use the plugin's documentation or inspect
its settings in `~/.octoprint/config.yaml`. Declaring a dictionary or list
reconciles that whole value; undeclared config paths are left untouched.

## Password behavior

Passwords are never printed and are entered into OctoPrint's CLI prompt rather
than placed in process arguments. A missing user is created idempotently.
Because OctoPrint intentionally stores only a one-way password hash, Ansible
cannot compare an existing password. Set `octoprint_reset_existing_password:
true` only when you intentionally want to reset it on every run.
