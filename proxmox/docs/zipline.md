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

Terraform manages the guest's root disk. The role locates the existing guest
by hostname before configuring Zipline.
The first administrator is `wbreiler`. Its password is generated inside the
container at `/opt/zipline/admin.json`, mode 0600. No default password exists.
Use the dashboard to upload videos and other files up to 512 MiB each.
For files over 25 MiB, the dashboard sends 25 MiB chunks through the proxy.
The proxy limits each request to 26 MiB, including multipart overhead.
Active HTML, JavaScript, and SVG content is refused.

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

## Publish a clip from the NAS

Move a finished clip into the SMB share's **Shared** folder or one of its subfolders.
A move within the same share keeps the media on the NAS. The publisher scans
every five seconds and waits until the file identity, size, and modification
time stay stable for ten seconds. Open **Shared clips** in the Zipline
dashboard to copy the public link. MP4, M4V, MOV, WebM, and MKV are eligible.
Zipline mirrors the directory hierarchy, including empty folders. For example,
`Shared/Overwatch` appears under **Shared clips → Overwatch**. Hidden entries
and symbolic links are excluded. Browser playback depends on the codecs.

For Discord, paste the clip's public viewer URL (`/view/<filename>`) in a
message. The copied public clip link also opens this viewer. The publishing
account stores `view.enabled` and `view.embedMediaOnly` in its Zipline user
settings. Enable both when recreating the account. The viewer includes the
video URL and, when available, a JPEG thumbnail in its Open Graph metadata.
The `/raw/` URL serves the media itself. The proxy preserves direct PNG
responses for the 16-character screenshot URLs used by the Mac and ShareX.

For a large 16:9 MP4, set `zipline_discord_clip` in local inventory to its
published `shared-<32 hex characters>.mp4` name. Apply the Zipline role with
proxy management enabled. The viewer advertises a full-duration 640×360
H.264/AAC preview. Browsers can still open the original. The worker prepares a
fast-start MP4 in RAM when it starts. It checks the viewer every 30 seconds and releases the buffer when the clip is withdrawn.
Every download first checks anonymous access with Zipline. The complete preview
has a known length and supports byte ranges. The worker caps its output at
8 MiB and encoding time at 90 seconds.

Move a clip out of Shared to withdraw it. The next scan removes its Zipline
record. Deleting a file in Zipline leaves the NAS file intact and suppresses
republication until a scan observes removal or a change. Anyone who already
downloaded the clip can keep their copy.

The guest stores a small JPEG preview, a symlink, and metadata. The original
video remains on Erebus and does not go through the HTTP upload limit.
The publisher uses the Zipline 4.8 file, folder, and thumbnail tables. Test
registration, seeking, and withdrawal after schema changes. Preserve
`/opt/zipline/shared-clips.json` with the Zipline database and uploads.

For deployment, create an ordinary Shared directory on the SMB filesystem.
Export only Shared using read-only NFS restricted to the cluster nodes.
Set `zipline_clips_export` in the local Proxmox variables. From `proxmox/`,
run `ansible-playbook zipline-clips-storage.yml --ask-vault-pass`. Declare a
read-only, shared Terraform bind mount from `/mnt/bindmounts/zipline-shared`
to `/srv/zipline-media/Shared` in the existing guest. Mount its dedicated
parent into Docker so the NFS submount retains `nosymfollow`.

Run `ansible-playbook zipline-clips.yml --ask-vault-pass` to install the
publisher. Its Compose override survives ordinary Zipline updates. For a
first-deployment pilot, pass `-e zipline_clips_start_timer=false` and run
`systemctl start zipline-shared-clips.service` inside the guest to scan.
Check the timer with `systemctl list-timers zipline-shared-clips.timer`.
