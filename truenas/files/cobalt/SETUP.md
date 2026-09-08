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
