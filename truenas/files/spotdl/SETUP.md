# spotDL

The scoped playbook installs the official spotDL Docker image as a TrueNAS
custom app. It uses the built-in web interface on port 8800, runs as a non-root
user, and stores configuration and downloads in dedicated host directories.

## Deploy

Run these commands from `truenas/`:

1. Copy `files/spotdl/vars.yml.example` to the ignored
   `artifacts/spotdl-vars.yml`. Set the existing storage paths, UID/GID, and LAN
   address. Pin the release image by its registry digest.
2. Create a protected configuration backup with `playbooks/backup.yml`.
   Override `truenas_backup_local_path` and `truenas_backup_remote_path` with
   fresh dated paths.
3. Check and deploy only this app:

   ```sh
   ansible-playbook playbooks/spotdl.yml -e @artifacts/spotdl-vars.yml --check --diff
   ansible-playbook playbooks/spotdl.yml -e @artifacts/spotdl-vars.yml -e truenas_allow_changes=true
   ```

4. Repeat the deployment command. Require `changed=0`, a healthy container,
   and an HTTP 200 response from `http://<LAN-address>:8800/`.

## Use

Open `http://<LAN-address>:8800/` and enter a Spotify track or playlist URL.
Downloads remain in the configured `spotdl_music_path`. Existing files are
skipped by default. The app has no authentication, so use it only on a trusted
LAN. Do not add a public port-forward.

An HTTP health check proves the web server works. It does not prove downloads
from Spotify or YouTube work. Those services can require account credentials
or cookies. Keep credentials in the app's private configuration directory.

Upstream: [spotDL v4.5.2 usage](https://github.com/spotDL/spotify-downloader/blob/v4.5.2/docs/usage.md).

## Web search workaround

The pinned 4.5.2 web handlers perform blocking Spotify metadata requests on the
event loop. `web_search.py` moves search and download metadata lookups into
short-lived subprocesses with a 30-second limit and kills them on timeout or
cancellation. Search cards use the metadata already returned by Spotify instead
of fetching complete track, artist, and album metadata for every result.
Downloads still fetch complete metadata. A lookup timeout does not prove that
Spotify or YouTube downloads work.

The launcher checks the version and exact upstream statements before applying
the workaround in memory. Review it before upgrading spotDL. The read-only
script mount and content label make deployment persistent and idempotent.
Run `python3 files/spotdl/test_web_search.py` from `truenas/` to check response
mapping, event-loop responsiveness, and worker cleanup.

Direct Spotify track, album, and playlist URLs now display track cards on the
search page. Use each card's download button. The original redirect abandoned
the active request and sent album URLs to the single-track download handler.
Album and playlist pagination remain inside the bounded worker. Download lookup
failures replace the loading button with an error instead of leaving a spinner.

Download buttons register a queue entry immediately and start a background task.
Page navigation does not cancel that task. Repeated clicks do not duplicate an
active track. Completed and failed results remain visible in the existing queue.
Jobs are held in memory and do not survive a container restart.

The image's yt-dlp 2026.07.04 returned HTTP 403 for audio transfers. The playbook
installs the checksum-verified 2026.8.19 wheel in a read-only dependency mount,
retaining the compatible yt-dlp-ejs 0.8.0 already in the image. Keep its version,
download URL, and checksum together when updating it.
Inside the image, `python test_web_search.py --upstream` additionally tests
immediate queue registration, detached work, duplicate prevention, and errors.
