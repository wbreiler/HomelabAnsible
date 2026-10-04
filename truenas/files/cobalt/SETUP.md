# Cobalt custom app

Deploys the upstream Cobalt API and an unmodified, locally built static web app
as one TrueNAS custom application. No datasets, host mounts, or GPU devices are
required. The API copies video streams and converts audio; it has no supported
NVENC/CUDA configuration. Browser encoding runs on the client.

## Build and configure

The API base image is pinned by digest in `Dockerfile.api`. The web
source matches its revision: `a636575b09de1fc55d9b8cd98cac88f5f2f16b42`
(Cobalt API 11.7.1). Rebuild the web image when upgrading the API or changing
the advertised address. Build dependencies use the upstream pnpm lockfile.

1. Build the API image on the Docker host with
   `docker build -t cobalt-api:a636575-youtube1 - < Dockerfile.api`.
   Clone <https://github.com/imputnet/cobalt> and check out that revision.
   Preserve the checkout’s `.git` directory in the build context. The web
   build reads Git metadata to generate `version.json`; an archive alone fails.
2. Copy `Dockerfile.web` into the checkout and `nginx.conf` into the checkout
   as `cobalt-nginx.conf`.
3. On the Docker host, build with the desired LAN address:

   ```sh
   docker build -f Dockerfile.web \
     --build-arg WEB_DEFAULT_API=http://192.0.2.10:9000/ \
     --build-arg WEB_HOST=192.0.2.10:9001 \
     -t cobalt-web:a636575 .
   ```

4. Copy `docker-compose.yml.example` to the ignored
   `truenas/artifacts/cobalt-compose.yml`. Replace the documentation address
   in both port bindings, `API_URL`, and `CORS_URL`. Keep machine-specific
   settings out of tracked files. The local web image uses `pull_policy: never`.
5. Validate that exact file on the Docker host using
   `docker compose -f <file> config --quiet`.
6. From `truenas/`, capture a fresh protected configuration backup per the
   project README, using unique dated local and remote backup path overrides.
7. Run only the dedicated application playbook:

   ```sh
   ansible-playbook playbooks/cobalt.yml --check --diff
   ansible-playbook playbooks/cobalt.yml -e truenas_allow_changes=true
   ansible-playbook playbooks/cobalt.yml -e truenas_allow_changes=true
   ```

The second apply must report `changed=0`. This playbook intentionally selects
only Cobalt, avoiding reconciliation of other possibly stale app definitions.
It requires an existing custom app and sends updates through the supported
TrueNAS Python API client. The Compose payload travels through protected
standard input, with `no_log` on configuration reads and updates.
The read-only discovery task also runs in check mode.

## Access and verification

Open port 9001 for the web interface; port 9000 is its API. These bindings are
for LAN access. Public hosting requires an HTTPS endpoint and upstream abuse
protection configuration. No router or DNS changes are part of this deployment.

Check the TrueNAS `cobalt` app is RUNNING, both containers are healthy, and the
API root reports the expected version and public API URL. Test a supported
public media link and follow the returned tunnel URL; HTTP health checks alone
do not establish that external providers work. Provider authentication and bot
restrictions can require additional configuration; no cookies are installed.

The first deployment also corrected the shared app role to omit catalog-only
fields for custom apps and avoid resolving missing `values` as a dictionary
method. Existing-app update behavior is unchanged.

## HTTPS reverse proxy

For a public endpoint, keep the existing host port bindings and use separate
TLS-enabled hostnames for the web interface and API. The unmodified frontend
uses only the origin of `WEB_DEFAULT_API`, so an API subpath does not work.
Rebuild the web image with `WEB_HOST=<public-web-hostname>` and
`WEB_DEFAULT_API=https://<public-api-hostname>/`. Use a distinct image tag,
update only the ignored Compose file, and retain the previous image for rollback.
Set `API_URL=https://<public-api-hostname>/` and
`CORS_URL=https://<public-web-hostname>` in that Compose file.

Configure both proxy hosts without asset caching:

| Hostname | Upstream | Path handling |
| --- | --- | --- |
| Public web hostname | Web host port 9001 | Preserve the path |
| Public API hostname | API host port 9000 | Preserve the path |

In Nginx Proxy Manager, select a valid certificate for each hostname and enable
Force SSL and HTTP/2 Support. Proxy the API root and all paths, including
`/session` and `/tunnel`. Do not append a path to the forward hostname.

Use the existing backup, check, apply, and idempotency procedure. Verify the
public API reports its HTTPS URL, the browser uses that API, and a returned
tunnel delivers a complete download. Public API access remains unauthenticated
unless separate access controls are configured.

## HLS compatibility patch

`Dockerfile.api` applies one checked source replacement to the pinned upstream
image: after recognizing an HLS playlist, set its Content-Type to
`application/vnd.apple.mpegurl`. The upstream image forwards a provider's
incorrect MIME type, causing FFmpeg 7.0.2 to reject extensionless internal
playlist URLs and return empty downloads. The web source remains unmodified.
Keep this Dockerfile alongside the upstream revision as the patch source.
Reassess the patch on upgrades; its build assertion fails if the expected
upstream code changes.

Live validation on 2026-09-08: web/API HTTP checks, direct video download,
image proxying, and FFmpeg audio conversion succeeded. The HLS patch changed
the upstream Bluesky video fixture from zero bytes to a nonempty remuxed stream
in an isolated container; the patched live API then delivered 65,536 video
bytes in the smoke test. The final apply reported `changed=0`. Vimeo returned a provider fetch error; a YouTube
sample returned an empty stream even with this fix. These provider cases are
not claimed working. No account cookies are configured. See the subsequent YouTube setup below.


## YouTube session provider

The custom app also runs BgUtils POT Provider 2.0.0, pinned by digest, on its
internal Docker network. It has no published host port. Cobalt loads tokens
from `http://youtube-session:4416/` and refreshes them every five minutes.
The provider shares the API's outbound public IP and stores sessions in memory.
Provider log storage is disabled because its diagnostics include session IDs.
The API waits for provider health on startup; initial token generation can
still take several seconds before YouTube requests are ready.

The older `imputnet/yt-session-generator` timed out obtaining tokens and is
not used. Cobalt 11.7.1 needs two additional checked build patches:

- Send JSON in the `/get_pot` POST, as required by the current provider.
- Select the session client for normal video qualities and audio-only requests,
  rather than only qualities above 1080p. `YOUTUBE_SESSION_INNERTUBE_CLIENT`
  selects `MWEB`; the default `WEB_EMBEDDED` was rejected by YouTube.

The earlier HLS MIME correction remains in the same API image. Subtitle
requests retain upstream's iOS-client behavior and are not covered by this
session-client fix. Rebuild using the current `Dockerfile.api` before applying
the Compose example. Use the same backup, check, apply, and idempotency procedure
above. The provider image is pulled automatically by TrueNAS.

Final YouTube validation on 2026-09-08 succeeded through the live API using
`https://www.youtube.com/watch?v=jNQXAC9IVRw`: complete video (742,286 bytes)
and audio-only (304,598 bytes) downloads both decoded with FFmpeg exit 0.
All three containers were healthy; all existing apps remained RUNNING and both
pools ONLINE. The second apply reported `changed=0`; project lint and syntax
checks passed. This verifies the tested public clip, not every YouTube video,
quality, account restriction, or subtitle path.

## Turnstile bot protection

The pinned API and frontend include Turnstile integration. Create a widget
restricted to the public web hostname. Managed mode allows Cloudflare to
request interaction when needed. Leave pre-clearance disabled unless separately
required by the site's security rules.

Add `TURNSTILE_SITEKEY`, `TURNSTILE_SECRET`, and a random `JWT_SECRET`
(at least 64 hexadecimal characters) to the API environment in the ignored,
mode-`0600` Compose file. Set `API_AUTH_REQUIRED: "1"`. Keep secret values
out of tracked examples, command arguments, and logs.

Back up TrueNAS, dry-run the dedicated Cobalt playbook, apply it, and repeat
until `changed=0`. No frontend rebuild is required: the frontend discovers
the site key from API metadata.

Verify that API metadata advertises the site key, an unauthenticated download
request returns `error.api.auth.jwt.missing`, and `/session` rejects missing
or invalid Turnstile tokens. Complete a real browser challenge and download
a supported public media fixture. Do not automate interactive CAPTCHA solving.
