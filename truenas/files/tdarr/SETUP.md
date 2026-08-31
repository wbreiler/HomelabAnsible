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
- Copy retained audio and subtitle streams without transcoding.
- Movies and TV retain English audio and English subtitles.
- Anime retains Japanese audio and English subtitles.
- Remove tagged audio/subtitle streams in other languages. Retain untagged
  streams because their language cannot be inferred safely.
- Copy chapters, global metadata, language tags, and attachments.
- Preserve HDR10 or HLG as 10-bit HDR; never tone-map it to SDR.
- Route Dolby Vision and HDR10+ titles through a video-copy remux path. Retain
  only the desired audio/subtitle languages while preserving the original
  dynamic-HDR HEVC bitstream unchanged.
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
- Use the English-language flow for Movies and TV and the Anime-language flow
  for Anime only after representative samples pass validation.

No path translator is needed because the internal server and node share the
same container and mounts.

## 4. Build the flow

Create two flows using the common encoding stages below:

- `AV1 VBR 75% - English audio and subs` for Movies and TV.
- `AV1 VBR 75% - Japanese audio, English subs` for Anime.

Use these stages:

1. **Input File**
2. **Check Video Codec**: codec `av1`
   - `File has codec` -> finish successfully without changing the file.
   - `File does not have codec` -> continue.
3. Add a **Custom JS Function** using `dynamic-hdr-route.js`:
   - Output 1 (Dolby Vision or HDR10+) -> the dynamic-HDR remux path.
   - Output 2 (no dynamic HDR) -> **Check HDR Video**.
4. On the dynamic-HDR remux path, use **Begin Command**, the same audio and
   subtitle language filters described below, **Set Container** to MKV, and
   **Execute**. Do not add a video encoder; the HEVC video must be stream-copied.
5. **Check HDR Video**
   - HDR -> require manual review, then use the 10-bit stage.
   - Not HDR -> continue through the SDR encode path.
6. Start a separate **Begin Command** path for HDR and SDR.
7. On the HDR, SDR, and dynamic-HDR remux paths, add two
   **Remove Stream By Property** stages:
   - Property: `tags.language`
   - Condition: `not_equals`
   - Movies/TV audio: keep `eng,en`
   - Anime audio: keep `jpn,ja`
   - All subtitles: keep `eng,en`
   - Limit each filter to its respective `audio` or `subtitle` codec type.
     Untagged streams are left untouched.
8. **Set Video Encoder** on only the HDR and SDR AV1 paths:
   - Output codec: `av1`
   - Hardware encoding: enabled
   - Hardware type: `nvenc`
   - Hardware decoding: enabled
   - FFmpeg preset: enabled, `veryslow`
   - FFmpeg quality: disabled; do not use constant QP for this flow
   - Force encoding: disabled
9. On the HDR branch only, add **10 Bit Video** before executing the command.
10. Add **Custom JS Function** after the HDR and SDR AV1 paths converge. Paste the
   contents of `source-relative-video-bitrate.js` into its **JS Code** input.
   This calculates a target of 75% of the source video bitrate from FFprobe's
   actual container bitrate (or actual file size and duration), after
   subtracting retained audio bitrates. When FFprobe omits a per-stream audio
   bitrate, as it commonly does for DTS-HD MA, the function uses MediaInfo's
   matching audio track and falls back to a conservative audio allowance if
   neither scanner supplies one. Do not use **Set Video Bitrate** with
   **Use percentage of input bitrate**: that plugin reads optional Matroska
   `BPS` tags, which can be stale and produce grossly oversized outputs.
11. Add **Custom Arguments** with these output arguments:

   ```text
   -rc vbr -preset p7 -tune hq -multipass fullres -spatial-aq 1 -temporal-aq 1 -rc-lookahead 32
   ```

   Tdarr 2.86.01's Set Video Encoder flow plugin intentionally omits `-preset`
   when the target codec is AV1, even when the preset switch is enabled, so the
   explicit P7 argument is required.
   On the Anime flow, append
   `-disposition:a:0 default -disposition:s:0 default` so the first retained
   Japanese audio and English subtitle streams are defaults.
12. **Set Container**: `mkv`, then **Execute**. Tdarr's command builder maps all
   existing streams and copies non-video streams without adding custom mapping
   arguments.
13. **Compare File Size Ratio**: lower bound `20`, upper bound `100`.
    - Within range -> continue.
    - Smaller than 20% -> manual review; an unexpectedly tiny output often
      indicates a quality or stream-selection mistake.
    - Larger than the source -> manual review; never replace automatically.
14. Run a quick health check on the accepted working file.
15. **Replace Original File** only on the health-checked path. A manually
    reviewed out-of-range result rejoins this path only after explicit review.

Constant-QP tests expanded already-efficient x265 sources to 176-244% of their
original size. QP values are not comparable between x265 and AV1 NVENC, and
constant QP places no bitrate ceiling on NVENC. The live flow instead targets
75% of the input video bitrate calculated from the actual file rather than
embedded `BPS` tags. The final size gate prevents replacement if copied streams
or encoder behavior still make the complete output larger.

## 5. HDR safeguards

Before allowing the HDR branch to reach **Begin Command**, inspect the title's
MediaInfo or FFprobe data:

- HDR10: process as 10-bit, retaining BT.2020 primaries, PQ transfer, mastering
  display metadata, and MaxCLL/MaxFALL where present.
- HLG: process as 10-bit, retaining BT.2020 primaries and ARIB STD-B67 transfer.
- Dolby Vision or HDR10+: stream-copy the video through the dynamic-HDR remux
  path; verify that the output still reports the original dynamic metadata
  before replacing the source.

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
5. Dolby Vision and HDR10+ samples for the video-copy remux route

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
