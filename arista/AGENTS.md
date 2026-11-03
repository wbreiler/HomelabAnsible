# AGENTS.md

Guidance for the homelab core switch. Read the [root guidance](../AGENTS.md)
and [README](README.md) before work. Run Ansible from `arista/`.

## Scope and protected access

The switch routes storage, IPMI, Proxmox hosts, and guests. A bad change can
disconnect all of them. Configuration changes require explicit user approval.
Management access uses the in-band Vlan1 SVI. The recorded Management1 port
is unused. Do not assume an out-of-band recovery path exists.

`site.yml` protects Ethernet1, Vlan1, Management1, accounts, AAA, SSH access,
and boot settings. Do not widen its allowlists or add a raw-command bypass
to reach those targets. Changes to protected management paths require a
confirmed out-of-band path and separate approval for the exact change.
DHCP is outside `site.yml`. The separate `network-boot.yml` entry point
manages only global DHCP boot options and explicitly reviewed new scopes on
VLANs 20 and 30. It preserves the existing guest scope and reservations.
EOS 4.28 cannot set BOOTP `next-server`. Firmware such as OVMF requires the
PXE proxy service documented in `proxmox/docs/network-boot.md`. Preserve Arista
address allocation. Do not replace DHCP scopes or add relays to work around it.
Its independent `arista_apply_network_boot` gate defaults to false. Read the
network boot section in the README before preview or application.

## Desired state and code boundaries

The general convergence entry point is `site.yml`, targeting group `arista`.
Its pre-task validates the complete local schema. The tracked example sets
`arista_apply_config: false`. With that gate false, configuration tasks skip,
so a successful run does not show the intended switch diff.

| Managed area | Contract |
| --- | --- |
| Physical interfaces | Only Ethernet2–11 and Ethernet43–48 |
| VLANs and SVIs | Only VLAN IDs 10, 20, 30, 40 and their corresponding SVIs |
| Layer-2 interfaces | `state: replaced` for each listed interface. Include every access/trunk attribute that must remain |
| Hostname, VLANs, interface descriptions, SVI addresses, routes | Merged resource state preserves unlisted configuration |
| Global settings and forced speeds | Explicit validated values through `eos_config` |

Preserve nested VLAN/address/route checks. Do not use `mode: access` because
the existing EOS module cannot report that default idempotently. Check mode
prints the layer-2 command list when it changes. Review that output.

The save handler runs only after a managed task changes, but EOS saves the
entire running configuration. Compare unrelated running/startup drift before
the first apply. A small Ansible diff does not limit what that save persists.

## Configuration and authentication

Real `inventory.yml`, `group_vars/arista.yml`, passwords, and discovery
artifacts remain ignored. Copy the sanitized examples before a new deployment.
Do not commit running configuration or raw switch output with secrets.

`ansible.cfg` enables host-key checks and uses libssh for `network_cli`.
OpenSSH multiplexing settings do not control that transport. A successful
manual SSH connection does not prove Ansible authentication. Keep credentials
in ignored configuration or an interactive password prompt, never argv.

Collection ranges are in `requirements.yml`. Deprecation suppression is local
to this project for the documented collection compatibility issue. Do not
copy it into other projects. Reassess it when those collections change.

The README's model, release, ports, and routes were checked on 2026-10-02.
They are a historical reference, not a fresh drift comparison.

## Validation and approved application

Run static checks first:

```sh
ansible-lint
ansible-playbook site.yml --syntax-check
git diff --check
```

For an approved device preview, set `arista_apply_config: true` in the local
configuration and run `ansible-playbook site.yml --check --diff` with the
appropriate authentication. The gate must remain true for a meaningful preview.

Before applying, review the complete commands, affected links, and recovery
path within the user's approved scope. Afterward, verify management access,
VLAN/routing state, and affected clients. Repeat the scoped run to check
idempotency. Do not infer service health from a successful configuration save.
