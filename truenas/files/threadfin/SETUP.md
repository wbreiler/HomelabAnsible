# Threadfin bridge for Plex

Threadfin 1.2.37 presents FastChannels as an HDHomeRun tuner to the existing
Plex server. The application runs at `https://threadfin.wbreiler.com/web/` and stores
its configuration and temporary files in
`/mnt/gaia/appdata/threadfin/{conf,temp}`.

From `truenas/`, after the protected configuration backup:

```sh
ansible-playbook playbooks/threadfin.yml --check --diff
ansible-playbook playbooks/threadfin.yml -e truenas_allow_changes=true
ansible-playbook playbooks/threadfin.yml -e truenas_allow_changes=true
```

The `Plex` feed in FastChannels includes LG Channels, FreeLiveSports, and
Adult Swim, with a 400-channel cap. Threadfin imports:

```text
https://fastchannels.wbreiler.com/feeds/plex/native/m3u
https://fastchannels.wbreiler.com/feeds/plex/native/epg.xml
```

These private names require the local DNS resolver inside the container.
After an approved appliance DNS change, refresh the affected app through the
TrueNAS app API and verify resolution inside its container. Existing Docker
containers can retain the previous resolver.

For generated stream links, configure `httpsThreadfinDomain` with the proxy
hostname, `httpsPort: 443`, and `forceHttps: true` in Threadfin settings.
First refresh the playlist so its cached upstream URLs use the FastChannels
HTTPS origin. Preserve the playlist IDs and channel mappings. The native
WebSocket API accepts one command per connection.

The playlist uses FFmpeg buffering and four tuners. Threadfin uses XEPG and
this FFmpeg option from the
[FastChannels Plex guide](https://github.com/kineticman/FastChannels/blob/development/docs/plex.md):

```text
-hide_banner -loglevel error -i [URL] -c:v copy -c:a libmp3lame -b:a 192k -ar 48000 -ac 2 -sn -f mpegts pipe:1
```

In Plex Web, open **Settings → Live TV & DVR → Set Up Plex DVR**. Add
`http://10.10.20.3:34400` as the tuner address. Select XMLTV guide data and
enter `http://10.10.20.3:34400/xmltv/threadfin.xml`. Plex configures DVRs
through its authenticated web app.

The existing Plex tuner retains its native discovery address and channel
mapping. The named web interface and upstream feed URLs do not require a DVR
rebuild. Do not delete the registered tuner just to replace its address.
