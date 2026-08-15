# Uptime Kuma Mini PC Ansible Configuration

Configures a Debian/Ubuntu host — a Mini PC or a Raspberry Pi, whatever's on
hand when a new site gets deployed — to run
[Uptime Kuma](https://github.com/louislam/uptime-kuma) in Docker, reachable
over Tailscale, kept up to date via `unattended-upgrades`, and provisioned
with an admin user, monitors, monitor groups, and a Discord notification
through Kuma's (unofficial) API.
Designed to run on more than one host at different physical locations at
once — see below. "Mini PC" throughout this doc just means "one of these
hosts"; the roles don't care which architecture it's running on.

- `apt_auto_update` — `apt update` now, plus `unattended-upgrades` for the OS
  going forward.
- `tailscale` — installs and authenticates Tailscale.
- `quorum_relay` — off by default; a small local relay service that lets 3+
  sites vote on shared-monitor outages instead of one static site always
  deciding. See "Three or more sites: quorum instead of static primary"
  below.
- `uptime_kuma` — installs Docker, runs Uptime Kuma in a container, then
  drives its admin-user setup, notification providers, monitor groups, and
  monitors through the third-party `uptime_kuma_api` Python client (Kuma has
  no official REST API for this). Reconciliation is additive: anything
  created by hand in the Kuma UI, or not listed in
  `uptime_kuma_monitors`/`uptime_kuma_groups`, is left alone.
- `bootstrap_lxc` / `pve_backup` — used once per Proxmox-hosted site
  (`bootstrap-lxc.yml`, not `site.yml`) to create the LXC that runs
  everything above, and to back it up to the existing PBS. Not needed for
  bare-metal sites (e.g. a Raspberry Pi). See "Proxmox-hosted sites" below.

## Setup

Run all commands from this directory so its `ansible.cfg` is used:

```bash
cd kuma
python3 -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
cp inventory.yml.example inventory.yml
cp group_vars/kuma_hosts.yml.example group_vars/kuma_hosts.yml
cp vault.yml.example vault.yml
install -d -m 0700 ~/.config/ansible/vault-passwords
install -m 0600 /dev/stdin ~/.config/ansible/vault-passwords/kuma
```

Enter the vault password, then press `Ctrl-D`. Then set up the first Mini PC
— see "Adding a Mini PC" below.

Encrypt the shared secrets:

```bash
ansible-vault encrypt vault.yml
```

Validate before applying:

```bash
ansible-lint
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml --check --diff
```

Apply:

```bash
ansible-playbook site.yml
```

## Adding a Mini PC

Every site in `inventory.yml`'s `kuma_hosts` group needs its own variables
file:

```bash
mkdir -p host_vars/<hostname>
cp host_vars/example/vars.yml.example host_vars/<hostname>/vars.yml
```

Then add the host to `inventory.yml` and edit `host_vars/<hostname>/vars.yml`
(location label, groups, monitors, peers). `group_vars/kuma_hosts.yml` and
the top-level `vault.yml` hold everything shared across every site (Kuma
version, admin credentials, Tailscale key, Discord webhook).

`ansible_host` for an x86 Mini PC site (`ms`, `tn`) is the *LXC's* IP, not
the Proxmox host's — see "Proxmox-hosted sites" below, that's a separate,
earlier step. For a bare-metal site (`tx`, the Pi), it's just the device's
own IP.

The `tx` Pi is online at `10.10.70.50` with system hostname `uptime-tx` and
Ansible inventory alias `tx`. Its Kuma application configuration still needs
`host_vars/tx/` before running `site.yml`. The `ms` and `tn` sites remain
planned; fill in `inventory.yml` and `host_vars/<hostname>/` as each comes
online.

## Proxmox-hosted sites (ms, tn)

The two x86 Mini PC sites run everything above inside a Proxmox LXC rather
than directly on the host OS — see the repo history/commit messages for why
(recovery unit becomes "recreate the LXC," not "re-image the machine"; PBS
backups give real disaster recovery). `tx` (the Pi) has no Proxmox build for
ARM, so it skips this section entirely and goes straight into `kuma_hosts`
as a normal bare-metal target.

**Everything here is DHCP** — the Proxmox host's own network config, and
the LXC's. These boxes get fully configured and Tailscale-joined on the home
network first, then physically shipped to their real location; a static IP
baked in at home would break the moment the network changes. Concretely,
two phases:

1. **At home.** Manually install Proxmox VE on the Mini PC (ISO installer,
   DHCP networking, not static — this one step isn't Ansible-automated).
   Note the DHCP-assigned management IP, add it to `inventory.yml`'s
   `pve_hosts` group, copy `group_vars/pve_hosts.yml.example` to
   `group_vars/pve_hosts.yml` and fill in the pinned template. Then two
   secret files: the shared Tailscale key + PBS server fingerprint in the
   top-level `vault.yml`, and this site's own PBS account (`cp -r
   host_vars/pve-example host_vars/<pve-hostname>`, then `ansible-vault
   encrypt host_vars/<pve-hostname>/vault.yml`) — each Proxmox-hosted site
   gets a distinct PBS account, unlike the Kuma-side secrets which are
   shared. Then:

   ```bash
   ansible-playbook bootstrap-lxc.yml --limit ms-pve --check --diff
   ansible-playbook bootstrap-lxc.yml --limit ms-pve
   ```

   This creates the LXC (Docker-nested, DHCP networking), joins the Proxmox
   host itself to Tailscale, and schedules a PBS backup job for the new LXC.
   It prints the LXC's DHCP-assigned IP at the end — put that in
   `inventory.yml`'s `kuma_hosts` entry for the site, then run `site.yml`
   normally against it (still on the home network at this point) to bring
   up Tailscale/Kuma/quorum inside the LXC and confirm everything
   works before it ships.

2. **After shipping.** Once the Mini PC is reconnected at its real location,
   its Tailscale identity persists automatically (no re-auth needed) even
   though its local IP changed. Swap `inventory.yml`'s `ansible_host` for
   that site — both the `pve_hosts` entry and the `kuma_hosts` entry — from
   the home-network IP to the Tailscale IP (`100.x.x.x`), so all future
   `ansible-playbook` runs happen over Tailscale instead of requiring local
   network access.

`roles/bootstrap_lxc` reuses the exact `/dev/net/tun` passthrough technique
already proven in `proxmox/roles/tailscale_router/tasks/main.yml` for the
same "Tailscale needs TUN inside an LXC" problem. `roles/pve_backup` reuses
`roles/tailscale` unmodified against the Proxmox host itself (it's just
another Debian host over SSH), then adds mnemosyne as a PBS storage target
and a daily backup job for the LXC, routed over Tailscale through the
already-deployed `tailscale_router` subnet router (`proxmox/`) — no new
subnet-router infrastructure needed.

**Unverified without real hardware:** Docker-in-unprivileged-LXC
occasionally needs `fuse-overlayfs` instead of the default `overlay2`
storage driver, depending on the Proxmox/kernel/storage combination. Watch
for this if `roles/uptime_kuma`'s Docker steps fail inside the LXC
specifically (works fine bare-metal on `tx`).

## Multiple sites, one notification per event

Every site checks the *same* shared infrastructure independently — that's
the point of running more than one, since a single site's flaky link
shouldn't be your only vantage point. But only one notification actually
fires per real event. Not a Kuma clustering feature (it has none) — two
plain rules, plus quorum voting once there are 3+ sites:

1. **Shared infra is defined once, deployed everywhere, notified once.**
   Put anything every site should check in `group_vars/kuma_hosts.yml`'s
   `uptime_kuma_shared_monitors` — every site gets an identical copy. Set
   `uptime_kuma_is_primary_notifier: true` on exactly one host (currently
   `ms`, in `host_vars/ms/vars.yml`); every other site gets `false`. Only the
   primary's copies of those monitors carry the Discord notification — every
   other site's copies still run and still show on that site's own
   dashboard, they just don't page. One real outage → one Discord message,
   from whichever site is primary. Site-specific gear (that site's own local
   network, a device only reachable from there) goes in that host's own
   `uptime_kuma_monitors` instead, and always notifies — there's no
   duplicate to dedup since no other site can even check it.

2. **Peers catch "the primary site itself is gone."** Set `uptime_kuma_peers`
   on each site to point at every other site's Tailscale IP:

   ```yaml
   # host_vars/ms/vars.yml
   uptime_kuma_peers:
     - name: "TN Mini PC (Greenbrier)"
       location: "TN"           # must match that peer's own uptime_kuma_location
       tailscale_ip: "100.x.x.x"
       is_primary: false        # true on exactly one peer fleet-wide
   ```

   The role turns each entry into a `<name> (peer)` HTTP monitor (checking
   that sibling's Kuma port over the private Tailscale link, not the public
   internet) with `uptime_kuma_peer_retries` retries before it alerts
   (default 3, one minute apart) so a momentary Tailscale reconnect doesn't
   page anyone. This is what tells you if `ms` (the primary notifier) drops
   off the network entirely — the other sites notice `ms` is unreachable and
   page about *that*. You'll get "MS Mini PC is down" instead of the
   specific service alert, which is enough to know to go look. It doesn't by
   itself make another site start paging on `ms`'s behalf — that's what
   quorum voting (below) is for, once there are 3+ sites to vote with.

## Three or more sites: quorum instead of static primary

With 3 sites, "who's right when two disagree" becomes a real vote: majority
of 3 is 2, so ties aren't possible the way they'd be with only 2 sites.
`roles/quorum_relay` implements this — set `uptime_kuma_quorum_relay_enabled:
true` on every site (still just one `uptime_kuma_is_primary_notifier: true`)
once `uptime_kuma_peers` lists every other site with a `location` and
`tailscale_ip`:

```yaml
# every site's host_vars/<hostname>/vars.yml
uptime_kuma_quorum_relay_enabled: true
uptime_kuma_peers:
  - name: "TN Mini PC (Greenbrier)"
    location: "TN"
    tailscale_ip: "100.x.x.x"
    is_primary: false   # true on exactly one site fleet-wide
  - name: "TX Pi"
    location: "TX"
    tailscale_ip: "100.x.x.x"
    is_primary: false
```

With this on, every quorum site's copy of `uptime_kuma_shared_monitors`
notifies through a small local relay service instead of Discord directly.
Kuma calls the relay locally (`127.0.0.1`, no network exposure); the relay
tags the event with its own site name and forwards it to the primary's
relay over Tailscale; the primary only pages Discord once a majority of
sites currently agree the target is down, and only once per down/up
transition (not once per site's report). One flaky path on one site can no
longer page alone, and it can no longer stay silently wrong either — the
other sites outvote it. See `HANDOFF.md` for the full design notes and
`roles/quorum_relay/test_quorum_relay.py` for the vote-tallying logic's
tests (run it directly: `python3 roles/quorum_relay/test_quorum_relay.py`).

Site-specific monitors and peer watchdogs are never quorum-gated — they
always notify straight to Discord, since there's nothing to vote on (only
one site can check them, or the "down" itself came from a direct
observation, not a disputed one).

## Monitors and groups

Two parallel sets, same shape, different scope:

- `uptime_kuma_shared_monitors` / `uptime_kuma_shared_groups` in
  `group_vars/kuma_hosts.yml` — deployed to every Mini PC, only the primary
  notifier pages for them. Use for infra every site can reach.
- `uptime_kuma_monitors` / `uptime_kuma_groups` in each
  `host_vars/<hostname>/vars.yml` — only that site, always pages. Use for
  gear only reachable from that one location.

Items in either need `name`, `type` (one of Kuma's own monitor types:
`http`, `port`, `ping`, `keyword`, `dns`, `docker`, ...), whatever fields
that type requires in Kuma (`url` for `http`; `hostname` + `port` for
`port`/`ping`), and optionally `group` naming an entry from the matching
groups list. Field names match Kuma's own monitor fields — check the Kuma UI
or the [`uptime_kuma_api`](https://github.com/lucasheld/uptime-kuma-api)
docs for the full list per type. Optional `critical: false` (default `true`)
routes that monitor to the quieter, no-mention notification tier — see
"Notifications" below.

```yaml
# group_vars/kuma_hosts.yml -- every site checks this, one of them pages
uptime_kuma_shared_groups:
  - name: "Shared Infra"
uptime_kuma_shared_monitors:
  - name: "Proxmox nyx"
    type: port
    hostname: "10.10.30.2"
    port: 8006
    group: "Shared Infra"
    interval: 60

# host_vars/ms/vars.yml -- only MS checks this, MS always pages
uptime_kuma_groups:
  - name: "MS Homelab"
uptime_kuma_monitors:
  - name: "MS site router"
    type: ping
    hostname: "10.0.0.1"
    group: "MS Homelab"
    interval: 60
```

Monitors are added or updated, never deleted — remove a monitor by hand in
the Kuma UI if it's no longer wanted.

## Notifications

Set `uptime_kuma_discord_webhook_url` (in the top-level `vault.yml`, shared
by every Mini PC) to have the role create **two** Discord notification
providers, same webhook and thread, different urgency:

- `uptime_kuma_notification_name` (default `"Discord"`) — includes
  `uptime_kuma_discord_prefix_message` (a mention/ping). The default for
  every monitor.
- `uptime_kuma_info_notification_name` (default `"Discord (Info)"`) — same
  channel/thread, no mention. Still visible, doesn't page you.

Any monitor (`uptime_kuma_monitors` or `uptime_kuma_shared_monitors`) can
set `critical: false` to use the Info tier instead of the default. Leave
`uptime_kuma_discord_webhook_url` blank to skip notification setup
entirely — no providers get created either way.

## Docker image updates

`uptime_kuma_version` is a pinned image tag, not `latest` — Ansible won't
silently move it out from under a working deployment. To find out when a
newer Uptime Kuma image is published, add it to `diun_watch_images` in
`proxmox/group_vars/proxmox_cluster.yml` (the central Diun instance polls
image registries directly, so it doesn't matter that these hosts run outside
Proxmox):

```yaml
diun_watch_images:
  - name: "louislam/uptime-kuma:{{ current pinned version }}"
    watch_repo: true
    sort_tags: "semver"
```

Diun posts to Discord when a newer tag appears. Bump
`uptime_kuma_version` in `group_vars/kuma_hosts.yml` and rerun
`ansible-playbook site.yml` to pick it up on every Mini PC at once.

## Monitoring Docker containers

Set `uptime_kuma_monitor_docker_containers: true` to mount the host's Docker
socket read-only into the Kuma container so it can add Docker-type monitors.
This grants root-equivalent host access to whatever runs in that container;
off by default.
