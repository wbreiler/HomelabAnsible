# Threadfin bridge for Plex

Threadfin 1.2.37 presents FastChannels as an HDHomeRun tuner to the existing
Plex server. The application runs at `http://10.10.20.3:34400/web/` and stores
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
http://10.10.20.3:5523/feeds/plex/native/m3u
http://10.10.20.3:5523/feeds/plex/native/epg.xml
```

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
