# LANCache

The scoped `playbooks/lancache.yml` installs a TrueNAS custom app with
digest-pinned LANCache monolithic and DNS images. Monolithic handles HTTP
caching and HTTPS passthrough. HTTPS content is not cached.

Add these settings to the ignored host `desired_state.yml`, with local values:

```yaml
lancache_bind_address: 192.0.2.10
lancache_root: /mnt/tank/appdata/lancache
lancache_upstream_dns: 1.1.1.1
lancache_disk_size: 1000g
lancache_timezone: America/Chicago
```

The existing parent dataset must exist. This playbook creates directories only.
`1000g` sets the Nginx cache target to 1000 GiB (approximately 1 TB).
This is an eviction target, not a dataset quota. Logs also consume disk space.
The cache starts eviction below 100 GiB of filesystem free space.

## Deploy

Run from `truenas/`. Inspect both TCP and UDP listeners before deployment,
including wildcard listeners and Docker port mappings. Ports 80 and 443 need
TCP; port 53 needs TCP and UDP. The playbook also checks TCP ports on first
deployment. Preserve the existing TrueNAS UI bindings.

Create a fresh protected configuration backup using `playbooks/backup.yml`,
with unique local and remote paths supplied as extra variables. Then run:

```sh
ansible-playbook playbooks/lancache.yml --check --diff
ansible-playbook playbooks/lancache.yml -e truenas_allow_changes=true
ansible-playbook playbooks/lancache.yml -e truenas_allow_changes=true
```

The second apply must report `changed=0`.

## Validate and enable a client

Set `CACHE_IP` to the configured bind address. These checks do not change
the client's DNS settings:

```sh
CACHE_IP=192.0.2.10
dig @"$CACHE_IP" lancache.steamcontent.com A +short
dig +tcp @"$CACHE_IP" lancache.steamcontent.com A +short
dig @"$CACHE_IP" example.com A +short
curl --fail --resolve "store.steampowered.com:443:$CACHE_IP" \
  https://store.steampowered.com/ -o /dev/null
```

The Steam queries must return the cache IP. The example.com query must return
public addresses. HTTPS must retain a valid upstream certificate.

To test caching, download the Steam installer twice through the cache:

```sh
test_dir=$(mktemp -d)
for attempt in 1 2; do
  curl --fail --silent --show-error --max-time 60 \
    --resolve "steamcdn-a.akamaihd.net:80:$CACHE_IP" \
    http://steamcdn-a.akamaihd.net/client/installer/SteamSetup.exe \
    -o "$test_dir/steam-$attempt.exe" || exit 1
done
test -s "$test_dir/steam-1.exe" &&
  cmp "$test_dir/steam-1.exe" "$test_dir/steam-2.exe"
```

Inspect `/data/logs/access.log` in the monolithic container for a `MISS`
followed by a `HIT`. Subsequent tests can produce two hits. These commands
download files only; do not execute them.

Configure one client's DNS server to the cache IP when ready. Do not configure
a public resolver as a secondary DNS server: clients can bypass the cache.
Client encrypted DNS can also bypass LANCache. This deployment does not change
DHCP, router DNS, appliance DNS, or client settings. Restore the client's
previous DNS settings to bypass the cache.

## Operations

The TrueNAS app is named `lancache`. Persistent data lives in the configured
root's `cache/` and `logs/` directories. Container stdout logs rotate at
10 MB with three files retained.

Use `midclt call -j app.stop lancache` to stop the app after clients restore
their previous DNS settings. This preserves the cache. Do not delete the app
or cache directories as part of ordinary troubleshooting.

Upstream: [LANCache documentation](https://lancache.net/docs/) and
[official Compose configuration](https://github.com/lancachenet/docker-compose).
