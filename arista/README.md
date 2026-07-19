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
| Hostname | `localhost` — not yet set |

## Status

Discovery in progress. `show running-config sanitized` still needed (requires
enable mode). Raw discovery output lives in `artifacts/` (gitignored).

## L3 / VLANs

The switch is the gateway (SVI) for each VLAN:

| VLAN | Name | SVI | Ports |
|---|---|---|---|
| 1 | default | 192.168.1.222/24 | Et1 (uplink) |
| 10 | ipmi | 10.10.10.2/27 | Et8–11 (+Et43–48 reserved, dark) |
| 20 | storage | 10.10.20.1/27 | Et2–7 |
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
| Et7 | atlas-idrac | vlan 20 | 1G |
| Et8–11 | prometheus-ilo, nyx-idrac, mnemosyne-idrac, erebus-ipmi | vlan 10 | 1G |

## Usage

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory.yml.example inventory.yml   # fill in credentials
ansible-playbook site.yml                # (playbook TBD after full discovery)
```
