# Plex media and authentication hardening

Plex uses its existing catalog application, configuration, libraries, and image
selection. Keep these two settings in the ignored appliance desired state:

```yaml
plex:
  allowed_networks: []
```

Set `read_only: true` on the additional storage entry mounted at `/media`.
Keep configuration, logs, application data, and transcode storage writable.
The Plex `allowedNetworks` preference must also be empty. An empty container
environment variable does not necessarily erase an existing preference.

## Before changing the application

1. Export a protected TrueNAS configuration backup.
2. Save the complete app configuration and Plex preferences with mode `0600`.
3. Check active sessions, DVR subscriptions, and optimization subscriptions.
4. Check the library database for optimized copies and their destinations.
5. Preserve complete nested app settings when calling `app.update`.

TrueNAS can replace omitted nested settings with defaults. For this change,
submit the complete existing `plex` and `storage` dictionaries with only the
authentication exceptions and media read-only flag changed. Preserve the
existing config/data/logs paths, transcode configuration, and image selector.
Use the supported middleware client and keep credentials out of arguments and
logs. Do not modify share permissions or dataset ACLs.

## Verified on 2026-10-21

- DVR was configured, with no recording or optimization subscriptions. The
  library database contained no active media paths under `Plex Versions` and
  no media proxy types associated with optimized copies.
- The app authentication exceptions and Plex `allowedNetworks` preference
  were empty after the restart. Unauthenticated library and settings reads
  returned HTTP `401` from the controller.
- The `/media` bind mount rejected an actual write with `EROFS`. Original
  app settings matched the saved configuration except for the two intended
  changes. A second comparison required no changes.
- Authenticated library/settings access succeeded. A direct media request
  returned HTTP `206` with 8 MiB. A forced H.264/AAC transcode returned an HLS
  segment that FFmpeg decoded for three seconds.
- Plex remained claimed on version `1.43.5.11029-6bf8af3f0`. The container was
  running with no automatic restarts. No TV-client or external playback test
  was performed.

The protected configuration export is an ignored artifact at
`artifacts/erebus-config-2026-10-21-plex-hardening.tar`. The original app values
and preferences are protected on the appliance under
`/mnt/gaia/appdata/plex/hardening-backup-2026-10-21/`. These files contain
credentials. Never commit or print their contents.

Future DVR recordings or optimized copies need a separate writable destination.
They cannot write into the read-only media mount. Keep playback checks separate
from proof of TV-client compatibility or external connectivity.
