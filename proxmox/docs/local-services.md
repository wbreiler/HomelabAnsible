# Local DNS and private HTTPS services

`local-services.yml` configures port-free HTTPS URLs on the existing Nginx
Proxy Manager guest. `files/local_dns.py` creates persistent A records through
the UniFi Network integration API. It does not edit generated dnsmasq files,
controller databases, DHCP, routing, public DNS, or router port forwards.

## Local configuration

Keep the real route list in ignored `group_vars/proxmox_cluster.yml`:

```yaml
local_services_proxy_vmid: 101
local_services_certificate: /etc/letsencrypt/live/example/fullchain.pem
local_services_certificate_key: /etc/letsencrypt/live/example/privkey.pem
local_services_routes:
  - name: spoolman.example.com
    address: 192.0.2.20
    port: 7912
```

The default proxy node is `prometheus`. Override `local_services_proxy_node`
when the guest moves. Terraform still owns the guest. These commands only
configure software in an existing, running guest.

Use an existing certificate that covers every name. The live deployment uses
NPM's existing wildcard certificate and its existing renewal process. Its
private key stays on the proxy. Never create conflicting NPM UI host entries
for these names. Ansible owns `/etc/nginx/conf.d/homelab-local-services.conf`.

Keep the matching DNS records in ignored `local-services.dns.json`:

```json
[
  {"domain": "spoolman.example.com", "ipv4Address": "192.0.2.10"},
  {"domain": "librespeed.home.arpa", "ipv4Address": "192.0.2.30"}
]
```

The proxy-backed records point to the proxy address. LibreSpeed points directly
to its HTTP guest, so a proxy cannot distort the bandwidth result. Verify live
guest addresses and their DHCP reservations before future changes.

## Apply

Run from `proxmox/`. First review and install the HTTPS routes:

```sh
ansible-playbook local-services.yml --check --diff
ansible-playbook local-services.yml
ansible-playbook local-services.yml
```

The first run compares the rendered configuration without modifying the guest.
An actual update validates Nginx before reload and restores the previous file
if validation or reload fails. A second successful run must report no changes.

Create an API key in UniFi Network's **Settings → Control Plane → Integrations**.
Store it in a local file with mode `0600`. Authenticate the gateway's SSH host
key before use. Review the proposed DNS additions first:

```sh
python3 files/local_dns.py \
  --ssh-target root@GATEWAY_ADDRESS \
  --identity-file ~/.ssh/cluster.pub \
  --key-file /private/tmp/homelab-unifi-api-key \
  --records local-services.dns.json
```

Repeat with `--apply` to create missing records. The script reads every existing
policy before writing. Conflicting names fail without replacement. Unrelated
records stay intact. Successful writes print their IDs for recovery. A partial
API failure leaves already-created records intact; rerun to add the remainder.
Repeat the command to verify `create: []` and the saved policies. Keep its output
outside Git because it contains the deployment's actual record names and IDs.

The key travels through SSH stdin, never argv. API requests run against gateway
loopback. SSH authenticates and encrypts the network connection; loopback TLS
does not require a publicly trusted gateway certificate. No key is saved on the
gateway. Remove the temporary local key file when finished.

## Verify

Use `dig @GATEWAY_ADDRESS NAME +short` and `curl -I https://NAME/` from a LAN
client. A successful HTTP response must also pass normal certificate validation.
Check the app's login and interactive functions in your own browser.

The route admission rule uses `$realip_remote_addr`, the actual connection peer.
It allows private IPv4, Tailscale IPv4, and loopback sources. Public IPv4 and
non-loopback IPv6 sources receive HTTP 403, even with forged forwarding headers.
This rule applies to both HTTP and HTTPS. Public DNS absence alone is not the
access control. Any upstream NAT that hides a public client behind a private
source would need separate enforcement.

`tests/verify_local_services_ingress.py` tests the installed configuration in an
isolated Linux network namespace. Run it as root inside the proxy guest. It
replaces only upstream responses and logs in a temporary configuration. It
tests every route for private HTTPS, private HTTP redirects, public denial, and
public denial with forged private forwarding headers. Production Nginx stays up.

```sh
python3 -m unittest discover -s tests -p test_local_dns.py
ansible-lint
```

Clients must use UniFi DNS, directly or through a resolver that forwards these
names to it. Browser secure DNS or an unrelated VPN resolver can bypass local
records. LANCache's upstream resolver must also preserve this path. DNS cannot
remove arbitrary non-HTTP service ports; these proxy routes cover web services.

The ignored `local-services.urls.md` contains links for the current deployment.
The HTTP `graf-nash` compatibility route remains owned by `centralized_logging`.

## Recovery

The prior proxy file, when present, is saved as
`/etc/nginx/conf.d/homelab-local-services.conf.previous`. Restore it, run `nginx -t`,
then run `nginx -s reload`. To retire a newly added route, remove only its entry
from the local desired list and rerun the playbook. Delete its matching DNS
policy in UniFi after reviewing the recorded policy ID. The DNS helper never
deletes or silently overwrites policies.
