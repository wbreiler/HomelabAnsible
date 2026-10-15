# YouTube archive

The scoped `playbooks/youtube.yml` deploys digest-pinned Pinchflat through the
TrueNAS custom-app API. It creates only the configured child of `gaia/Archive`.
The video dataset uses 1 MiB records, LZ4 compression, and `atime=off`. Sync,
checksums, and deduplication retain their inherited settings. The parent is
not modified. Application SQLite data stays in separate appdata storage.

## Deployment

Run from `truenas/`. Copy `files/youtube.yml.example` to an ignored local
variable file. Add an optional `youtube_sources` list of channel/playlist URLs.
Back up TrueNAS configuration before the first mutating run.

```sh
ansible-playbook playbooks/youtube.yml --check -e @artifacts/youtube-vars.yml
ansible-playbook playbooks/youtube.yml -e @artifacts/youtube-vars.yml -e truenas_allow_changes=true
```

Repeat the deployment and require `changed=0`. The LAN UI is port 8945 on the
configured address. Select **YouTube Archive** for additional sources.
Sources include historical videos and future uploads, with no retention limit.
Fast indexing checks new uploads every ten minutes; Pinchflat also schedules
full channel scans. Private, deleted, unavailable, or restricted videos may
require additional access and are not guaranteed to download.

The media profile selects the best resolution up to 8K and saves MKV, metadata,
and thumbnails. Subtitle downloads are disabled because YouTube rate-limited
them during verification. MKV keeps tracked file paths stable
when Tdarr replaces a file. No channel subscriptions are removed automatically.

## Tdarr

Only the archive child mounts at `/youtube`. The existing Movies flow is
copied to `youtubeAv1`, with audio/subtitle language filters disabled. Existing
AV1 skip logic, NVENC, HDR protections, output size checks, and health checks
remain. Other libraries and flows retain their settings. This is lossy AV1
transcoding and replaces originals after the existing flow's checks pass.

The `YouTube` library watches video files and holds new files for five minutes.
Partial download files and sidecar metadata do not match its extension filter.
The existing GPU worker is enabled. The flow can require manual review for
outputs outside its size limits. An AV1 source may need no transcode.

The first mount update refuses to restart Tdarr during an active encode. It
pins the running image digest and exports a SQLite backup plus Compose config
under the existing Tdarr `Backups/youtube-*` directory, mode 0700. The database
copy contains authentication material and has mode 0600. Restore only with
Tdarr stopped and with separate user authorization. No automatic deletion or
database rollback occurs.

## Verification

The helper reads the existing Tdarr key locally and uses the authenticated API;
it never changes the appliance database or prints the key. API writes have
read-back assertions. Pinchflat uses its running application's release RPC and
context functions for profiles and sources. Check mode does not mutate either.

Verify the UI, dataset properties, downloaded media, and active GPU worker.
Configuration convergence alone does not establish a successful YouTube download
or a completed Tdarr transcode. Back up Pinchflat appdata as well as videos.
