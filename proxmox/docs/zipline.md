# Screenshot uploads

`https://i.wbreiler.com/<random-name>.png` serves the uploaded image directly.
Uploads require a Zipline API token. Image URLs are public and have no default
expiration. Anyone with a link can view it. Cloudflare caches eligible images.
The dashboard is at https://i.wbreiler.com/dashboard.

## Ansible

Enable `install_zipline: true` in local variables. From `proxmox/`:

```sh
ansible-playbook site.yml --tags zipline -e install_zipline=true --ask-vault-pass
```

The role pins both Docker images by digest. It preserves the PostgreSQL
and upload directories, the application secret, and administrator credentials.
Existing data is never deleted. Check mode validates configuration but skips
container operations. Back up `/var/lib/zipline` and `/opt/zipline` together.
Review database migrations before changing either pinned image.

Fresh deployment defaults use VMID 126 on Prometheus, 2 CPUs, 2 GiB RAM,
and a 32 GiB root disk. VMID 114 remains configured for Minecraft.
Verify IDs against live guests and local server configuration before reuse.
The first administrator is `wbreiler`. Its password is generated inside the
container at `/opt/zipline/admin.json`, mode 0600. No default password exists.
Uploads are limited to 25 MiB. Active HTML, JavaScript, and SVG content is refused.

## Public ingress

DNS is a proxied Cloudflare A record for `i.wbreiler.com` using the existing
public ingress address. The existing NPM container terminates HTTPS.
The role does not manage Cloudflare DNS or issue certificates.

Before setting `zipline_manage_proxy: true`, issue its certificate inside NPM:

```sh
certbot certonly --non-interactive --agree-tos --email YOUR_EMAIL \
  --webroot -w /data/letsencrypt-acme-challenge \
  --cert-name homelab-zipline -d i.wbreiler.com
```

An HTTP server for this hostname must first expose the existing ACME challenge
location. The role installs `/etc/nginx/conf.d/homelab-zipline.conf`, validates
Nginx, restores its previous file if validation fails, and reloads Nginx.
After certificate issuance, reconcile ingress from `proxmox/`:

```sh
ansible-playbook site.yml --tags zipline -e install_zipline=true \
  -e zipline_manage_proxy=true --ask-vault-pass
```

It resolves the current application address on each run. Its proxy defaults
identify NPM as VMID 101 on Prometheus. Keep the application DHCP lease stable
or rerun the role after an address change.

The proxy buffers larger uploads in `/tmp/nginx/body`. The role creates this
directory with a systemd-tmpfiles rule and excludes `/tmp/nginx` from age-based
cleanup. Without it, larger screenshots return HTTP 500 while small images work.

Certbot's existing timer renews the certificate. A deploy hook at
`/etc/letsencrypt/renewal-hooks/deploy/reload-nginx` validates and reloads Nginx.
This standalone configuration is outside NPM's proxy-host dashboard.
Public image paths must remain accessible without Cloudflare Access login.
Cloudflare Browser Integrity Check remains enabled. The Mac uploader sends
a descriptive User-Agent. A test with Discord's User-Agent returned the image.

## Mac

The installed Quick Action is **Upload Screenshot**. Its assigned shortcut is
**Control + Option + Command + U**. Select a region. The action uploads the
image and copies its extensionless direct URL to the clipboard. Escape cancels the action.
macOS can request screen capture permission on first use.

The client is installed at `~/.local/bin/screenshot-upload`, with its token
at `~/.config/zipline/token`, mode 0600. Administrator credentials are in
`~/.config/zipline/admin.json`, mode 0600. Do not share either file.
The client uses Apple's Python 3, screenshot tool, clipboard tool, and
notification tool. No extra Python packages are required.

If the shortcut does not appear immediately, open System Settings > Keyboard
> Keyboard Shortcuts > Services > General and enable **Upload Screenshot**.
The Automator source is `files/zipline/Upload Screenshot.workflow`.

## ShareX

Import `~/Downloads/Zipline.sxcu` on Windows. This file contains your token.
In ShareX, select **Destinations > Image uploader > Custom image uploader**
and select **i.wbreiler.com**. Enable **Upload image to host** and
**Copy URL to clipboard** under **After capture tasks**.

You can regenerate the configuration from Zipline's user settings generator.
The uploader posts multipart field `file` to `/api/upload`. Its Authorization
header contains the API token. The returned URL is `{json:files[0].url}`.

## Verification

```sh
python3 tests/test_zipline_client.py
ansible-lint
ansible-playbook -i tests/test-inventory.yml site.yml --syntax-check
```

Live verification checked login, upload, public HTTP 200 with `image/png`,
matching image bytes, denied anonymous uploads, and repeat-run convergence.
Actual Discord rendering, Windows ShareX operation, and the Mac capture
shortcut require user interaction and remain unverified.
