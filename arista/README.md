# arista

Ansible-managed config for the homelab core switch — it carries the storage,
IPMI, and Proxmox VLANs and is the L3 gateway for all of them.

## Target

| Setting | Value |
| --- | --- |
| Address | `192.168.1.222` (SVI Vlan1; Management1 port is unused/down) |
| Model | Arista DCS-7050SX-64 (48x SFP+ + 4x QSFP+) |
| EOS | `4.28.12M` |
| Auth | `admin` with password (SSH) |
| Hostname | `arista-nash` (managed by `site.yml`) |

## Status

Discovery complete — sanitized running-config and raw output live in
`artifacts/` (gitignored). Those files are observations, not desired state:
the captured snapshot predates the managed hostname and Ethernet7 corrections.

Reusable automation remains tracked in `site.yml`. Machine-specific desired
values live in ignored `group_vars/arista.yml`, copied from the tracked
`group_vars/arista.yml.example`. Only the hostname and Ethernet7 correction
are managed so far; the remainder of the observed switch configuration is
deliberately untouched.

Known config quirks (observed, deliberately untouched):

- Et5/Et6 are access ports but carry leftover `switchport trunk *` lines
  (ignored in access mode); Et3 has a stray `switchport access vlan 20` under
  trunk mode. (Et7's were cleaned when `site.yml` moved it to VLAN 10.)
- `ip route 192.168.1.0/24 192.168.1.1` is redundant (directly connected via
  Vlan1).
- Management1 has an IP (10.30.16.100/20) but the port is down/unused.

## L3 / VLANs

The switch is the gateway (SVI) for each VLAN:

| VLAN | Name | SVI | Ports |
|---|---|---|---|
| 1 | default | 192.168.1.222/24 | Et1 (uplink) |
| 10 | ipmi | 10.10.10.2/27 | Et7–11 (+Et43–48 reserved, dark) |
| 20 | storage | 10.10.20.1/27 | Et2–6 |
| 30 | proxmox-hosts | 10.10.30.1/26 | Et2–4 |
| 40 | proxmox-guests | 10.10.40.1/24 | Et2–4 |

## Port map (connected)

| Port | Device | Mode | Speed |
|---|---|---|---|
| Et1 | uplink-ucg (AccessPanel) | trunk | 1G |
| Et2 | atlas | trunk | 10G |
| Et3 | prometheus | trunk | 10G |
| Et4 | nyx | trunk | 10G |
| Et5 | erebus (TrueNAS) | vlan 20 | 10G |
| Et6 | mnemosyne (PBS) | vlan 20 | 10G |
| Et7–11 | atlas-idrac, prometheus-ilo, nyx-idrac, mnemosyne-idrac, erebus-ipmi | vlan 10 | 1G |

## Usage

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory.yml.example inventory.yml
cp group_vars/arista.yml.example group_vars/arista.yml
# Edit both ignored local files before running anything.
ansible-playbook site.yml --ask-pass     # or set ansible_password in inventory.yml
```

Always preview switch changes first:

```bash
ansible-playbook site.yml --ask-pass --check --diff
```
