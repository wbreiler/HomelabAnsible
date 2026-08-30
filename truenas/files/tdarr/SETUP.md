# Tdarr setup on erebus

This guide is tailored to the single-container Compose stack in this directory,
its internal Tdarr node, the RTX 5050, and the existing media paths on
`erebus`. It favors safe replacement over maximum compression: one GPU worker,
original audio/subtitles/chapters, no resolution change, and manual validation
before processing a whole library.

## Encoding policy

- Output container: Matroska (`mkv`).
- Output video: AV1 through NVIDIA NVENC (`av1_nvenc`).
- Skip files whose primary video stream is already AV1.
- Do not resize, deinterlace, or tone-map by default.
- Copy every audio and subtitle stream without transcoding.
- Copy chapters, global metadata, language tags, and attachments.
- Preserve HDR10 or HLG as 10-bit HDR; never tone-map it to SDR.
- Route Dolby Vision and HDR10+ titles to manual review. Dynamic HDR metadata
  is not reliably preserved by a generic Tdarr/FFmpeg AV1 conversion, and
  client support for AV1 plus those formats is less predictable than HDR10.
- Replace an original only after health checking and confirming the result is
  smaller. Keep a backup until each content category has been playback-tested.

NVENC AV1 is fast, but it is still lossy. Do not transcode an AV1 file again,
and do not expect a remux-quality source to remain visually lossless.

## 1. Install without starting work

1. In TrueNAS Apps, create a custom app named `tdarr` using
   `docker-compose.yml` from this directory.
2. Do not change the `/media` and `/temp` host paths used by the internal mapped
   node.
3. Open `http://10.10.20.3:8265` and complete the initial account setup.
4. Confirm the node named `erebus-rtx5050` appears. It intentionally starts
   paused.
5. Leave the node paused until the tests below pass and the first library and
   flow are configured.

The server API port is `8266`; it is not the web interface.

## 2. Verify the RTX 5050 inside the node

From an `erebus` shell, these checks are read-only:

```bash
docker exec tdarr nvidia-smi
docker exec tdarr ffmpeg -hide_banner -h encoder=av1_nvenc
```

Both must succeed. The first command should name the RTX 5050. The second must
show the `av1_nvenc` encoder. Do not begin a library scan if either fails.

## 3. Add libraries

Create three libraries so each can be tested and scheduled independently:

| Library | Source | Transcode cache |
| --- | --- | --- |
| Movies | `/media/movies` | `/temp/movies` |
| TV | `/media/tv` | `/temp/tv` |
| Anime | `/media/anime` | `/temp/anime` |

For the initial rollout:

- Disable folder watching and scheduled scans.
- Do not automatically add the entire library to the transcode queue.
- Use the same flow for all three libraries only after one sample from each
  relevant content type passes validation.

No path translator is needed because the internal server and node share the
same container and mounts.

## 4. Build the flow

Create a Flow named `AV1 NVENC - preserve streams`. Use these stages:

1. **Input File**
2. **Check Video Codec**: codec `av1`
   - `File has codec` -> finish successfully without changing the file.
   - `File does not have codec` -> continue.
3. **Check HDR Video**
   - HDR -> route through the HDR safeguards below.
   - Not HDR -> continue through the SDR encode path.
4. **Begin Command**
5. **Set Container**: `mkv`
6. **Set Video Encoder**
   - Output codec: `av1`
   - Hardware encoding: enabled
   - Hardware type: `nvidia`
   - Hardware decoding: enabled
   - FFmpeg preset: enabled, `p7`
   - FFmpeg quality: enabled, start at `24`
   - Force encoding: disabled
7. On the HDR branch only, add **10 Bit Video** before executing the command.
8. **Custom Arguments** output arguments:

   ```text
   -map 0 -map_metadata 0 -map_chapters 0 -c:a copy -c:s copy -c:d copy -c:t copy
   ```

   Inspect Tdarr's generated command preview. There must be exactly one video
   encoder selection for the primary video stream, and it must be
   `av1_nvenc`. If the plugin version produces conflicting `-map` or `-c:v`
   arguments, remove this Custom Arguments stage and use Tdarr's individual
   stream-copy plugins instead; do not run an ambiguous command.
9. **Execute**
10. Run a thorough health check on the working file.
11. **Compare File Size Ratio**: lower bound `35`, upper bound `100`.
    - Within range -> continue.
    - Smaller than 35% -> manual review; an unexpectedly tiny output often
      indicates a quality or stream-selection mistake.
    - Larger than the source -> discard the working file and keep the original.
12. **Replace Original File** only on the accepted path.

Quality `24` is a conservative starting point, not a universal optimum. Test
`22`, `24`, and `26` on representative material: lower values retain more
quality and produce larger files. Do not judge quality from file size alone.

## 5. HDR safeguards

Before allowing the HDR branch to reach **Begin Command**, inspect the title's
MediaInfo or FFprobe data:

- HDR10: process as 10-bit, retaining BT.2020 primaries, PQ transfer, mastering
  display metadata, and MaxCLL/MaxFALL where present.
- HLG: process as 10-bit, retaining BT.2020 primaries and ARIB STD-B67 transfer.
- Dolby Vision or HDR10+: send to manual review and leave the source unchanged
  unless a test encode proves the required dynamic metadata and Plex playback
  survive on every important client.

Do not hard-code one title's mastering-display or MaxCLL values into the flow;
those values vary by source. Current FFmpeg/NVENC can pass frame HDR metadata,
but the result must be confirmed on the produced file rather than assumed.

## 6. Validate before bulk processing

Run only one GPU transcode worker. Keep the node paused except while testing.
Queue copies or otherwise-backed-up examples of:

1. 1080p SDR H.264
2. 1080p SDR HEVC
3. 2160p HDR10 HEVC
4. One title with multiple audio and subtitle tracks
5. Dolby Vision and HDR10+ samples for the skip/manual-review route

For every output, verify:

- video codec is AV1;
- HDR output remains 10-bit and retains its original color primaries, transfer
  characteristic, matrix, mastering display, and content-light metadata;
- every audio/subtitle stream, language tag, forced/default disposition,
  chapter, and attachment is present;
- duration and frame count are sensible;
- Plex direct-plays it on the intended clients and does not show washed-out or
  clipped HDR;
- the original is not replaced when the output is larger or fails validation.

Only after all categories pass should folder watching or scheduled scanning be
enabled. Start with Movies, monitor several completed jobs, then enable TV and
Anime separately.

## 7. Operational defaults

- Keep one GPU transcode worker until temperatures, stability, Plex contention,
  and output quality are known.
- Keep CPU transcode workers at zero; the configured CPU worker is for health
  checks only.
- Keep `/temp` on `/mnt/gaia/appdata/tdarr/transcode_cache`; do not put cache
  files in the media datasets.
- Review errors before retrying. Never create a flow that repeatedly encodes
  its own AV1 output.
- Back up Tdarr's `/app/server` and `/app/configs` data before major flow
  changes.

## References

- [Tdarr Docker Compose](https://docs.tdarr.io/docs/installation/docker/run-compose/)
- [Tdarr mapped nodes](https://docs.tdarr.io/docs/nodes/nodes/)
- [Tdarr Set Video Encoder](https://docs.tdarr.io/docs/plugins/flow-plugins/index/ffmpegCommand/Set%20Video%20Encoder/)
- [Tdarr Check HDR Video](https://docs.tdarr.io/docs/plugins/flow-plugins/index/video/Check%20HDR%20Video/)
- [NVIDIA FFmpeg acceleration](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)
- [NVIDIA HDR metadata behavior](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html)
