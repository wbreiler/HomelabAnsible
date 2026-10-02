# arista

Ansible-managed config for the homelab core switch — it carries the storage,
IPMI, and Proxmox VLANs and is the L3 gateway for all of them.

## Recorded target

Key authentication as `admin` was verified on 2026-10-02 after the user added
`~/.ssh/cluster.pub`. Live checks confirmed the model, EOS release, hostname,
interface state, VLAN interfaces, and routes below. Full running/startup drift
has not been compared. The client profile tries the agent-held key first and
retains password fallback.

| Setting | Value |
| --- | --- |
| Address | `192.168.1.222` (SVI Vlan1; Management1 port is unused/down) |
| Model | Arista DCS-7050SX-64 (48x SFP+ + 4x QSFP+) |
| EOS | `4.28.12M` |
| Auth | `admin` with agent-held cluster SSH key; password fallback retained |
| Hostname | `arista-nash` (managed by `site.yml`) |

## Status

Earlier discovery captured sanitized running-config and raw output in
`artifacts/` (gitignored). Those files are observations, not desired state:
the captured snapshot predates the managed hostname and Ethernet7 corrections.

Reusable automation remains tracked in `site.yml`. Machine-specific desired
values live in ignored `group_vars/arista.yml`, copied from the tracked
`group_vars/arista.yml.example`. The schema covers VLANs 10–40,
Ethernet2–11 and Ethernet43–48, SVI addresses, global routing, and static routes.
Do not assume the historical hostname and Ethernet7 corrections are the only
current differences. Confirm the actual device diff before applying. DHCP
configuration is outside `site.yml`.

Application is independently gated by `arista_apply_config`, which defaults to
`false` in the tracked example. The playbook still validates the complete local
desired-state schema while the gate is false, but every configuration task is
skipped. Set it to `true` in the ignored local file only for an approved check
or apply.

Ethernet1, Vlan1, Management1, users, AAA, SSH authentication, boot settings,
and secret-bearing unsupported-transceiver configuration are permanently
excluded. They require a separately confirmed out-of-band management path.

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

## Port map (live status, 2026-10-02)

| Port | Device | Mode | Speed |
|---|---|---|---|
| Et1 | uplink-ucg (AccessPanel) | trunk | 10G, connected |
| Et2 | atlas | trunk | 10G |
| Et3 | prometheus | trunk | 10G |
| Et4 | nyx | trunk | 10G configured, disconnected |
| Et5 | erebus (TrueNAS) | vlan 20 | 10G |
| Et6 | mnemosyne (PBS) | vlan 20 | 10G |
| Et7–11 | atlas-idrac, prometheus-ilo, nyx-idrac, mnemosyne-idrac, erebus-ipmi | vlan 10 | 1G |

The active routing table has a default route via `192.168.1.1` on Vlan1 and
connected routes for VLANs 1, 10, 20, 30, and 40. The VLAN port column above
includes configured ports; disconnected Et4 is absent from active membership.

## Usage

Test the installed key from the current Mac with `ssh admin@192.168.1.222`.
Other controllers must select their corresponding agent-held key. These SSH
checks do not establish Ansible `network_cli` authentication or configuration
convergence.

```bash
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
cp inventory.yml.example inventory.yml
cp group_vars/arista.yml.example group_vars/arista.yml
# Edit both ignored local files and leave arista_apply_config: false while
# reviewing the complete desired state.
```

Run static validation before connecting to the switch:

```bash
ansible-lint
ansible-playbook site.yml --syntax-check
```

For an approved live preview, set `arista_apply_config: true` locally and use
check mode. Without that gate, the configuration tasks intentionally skip and
the preview cannot show the intended device diff:

```bash
ansible-playbook site.yml --ask-pass --check --diff
```

After reviewing the complete diff and confirming a recovery path, omit
`--check` to apply. Use `--ask-pass` or set `ansible_password` only in the
ignored `inventory.yml`; never put the password in a command argument or a
tracked file.

The project uses `ansible-pylibssh` explicitly for `network_cli`; legacy
OpenSSH multiplexing arguments and the deprecated Paramiko fallback are not
used. Deprecation display is disabled only for this project because the
supported `arista.eos` 12.1.x and `ansible.netcommon` 8.5.x releases still call
APIs that ansible-core 2.21 has deprecated. Re-enable it when those collections
publish replacements.

SVI addresses are merged rather than destructively replaced until a current
live discovery confirms that no secondary addresses exist. The save handler
runs only after an Ansible-managed task changes, but EOS saves the entire
running configuration; review any unrelated running/startup drift before the
first apply.

Layer-2 configuration is the exception to the generally additive resource
states: `arista_l2_interfaces` uses `state: replaced` for each listed port.
Define every access/trunk attribute that must remain on those ports and review
the check-mode `commands` output. Do not set `mode: access`; the EOS resource
module cannot report that default idempotently.
