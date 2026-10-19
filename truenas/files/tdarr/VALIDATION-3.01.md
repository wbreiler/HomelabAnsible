# Tdarr 3.01 validation — 2026-10-19

## Result

All 15 isolated cases passed on Tdarr Server and Node `3.01.00` with the RTX 5050.
The tests used generated media and small upstream test samples.
The test container had no production media mounts.

## Runtime and recovery

- Image: `ghcr.io/haveagitgat/tdarr:3.01.00@sha256:5b3b8d4e54f41738d12ff71705cf8eb8e90fcbcc05209c331853aef119879992`.
- NVIDIA driver: `570.172.08`. FFmpeg: `7.1.4-jellyfin`.
- Test and production community-plugin revision: `87893f3f5c2fe4cc9ba09e141a3deeb794ae2880`.
- The live queue drained before the update. Its node stayed paused throughout the tests.
- Protected recovery files on Erebus: `/root/tdarr301-validation-20261019/`.
  This directory contains the appliance configuration, stopped Tdarr data/configuration archive, and original Compose/flow/library/node settings.
  Configuration backups have mode `0600`. The directory has mode `0700`.

## Flow corrections

The tests found these existing flow problems. They did not establish that Tdarr 3.01 introduced them.

1. Anime lacked the MP4 subtitle conversion stage already used by Movies/TV and YouTube.
   The corrected flow converts retained `mov_text` subtitles to SubRip and removes incompatible MP4 data streams before Matroska output.
2. Anime default-track arguments cleared forced-subtitle flags.
   Additive `+default` arguments now retain those flags.
3. FFmpeg assigned default flags when every source track had default disabled.
   `preserve-stream-metadata.js` explicitly copies retained track dispositions, including zero flags.
4. FFmpeg omitted the Dolby Vision MP4 configuration box during remuxing.
   The same helper enables `-strict unofficial` for Dolby Vision MP4 output.
   Video payloads and Dolby Vision signaling now survive the tested remux.

Copies of the three production flows ran in the isolated instance.
The corrected definitions were then applied to production while its node remained paused.
A second reconciliation required no further changes.

The production queue was restored to its original unpaused state after the tests.
YouTube was already absent from the library list before this maintenance.
The user approved its restoration below TV. The restored library converges with
Movies priority `0`, TV `1`, Anime `2`, and YouTube `3`.

## Cases

| Case | Result | Output | SSIM |
| --- | --- | --- | --- |
| sdr-english | PASS | av1 yuv420p / 192 frames | 0.999322 |
| sdr-anime | PASS | av1 yuv420p / 192 frames | 0.999322 |
| sdr-youtube | PASS | av1 yuv420p / 192 frames | 0.999322 |
| hdr10 | PASS | av1 yuv420p10le / 192 frames | 0.998571 |
| hlg | PASS | av1 yuv420p10le / 192 frames | 0.998571 |
| dolby-vision | PASS | Byte-identical HEVC passthrough | — |
| hdr10plus | PASS | Byte-identical HEVC passthrough | — |
| size-gate | PASS | Held 276,495-byte AV1 output; 30,326-byte source unchanged | — |
| already-av1 | PASS | Byte-identical AV1 passthrough | — |
| dolby-vision-multi | PASS | HEVC remux; byte-identical video payload | — |
| hdr10plus-multi | PASS | HEVC remux; byte-identical video payload | — |
| mp4-english | PASS | av1 yuv420p / 192 frames | 0.999619 |
| mp4-anime | PASS | av1 yuv420p / 192 frames | 0.999619 |
| mp4-youtube | PASS | av1 yuv420p / 192 frames | 0.999637 |
| hdr10-4k | PASS | av1 yuv420p10le / 72 frames | 0.998924 |

## Output checks

- Resolution, decoded frame count, duration within 80 ms, chapter titles, and chapter timing.
- English/Japanese language selection, YouTube retention of all languages, forced/default dispositions, subtitle text, and attachment payloads. Retained audio payloads match by SHA-256.
- HDR10/HLG 10-bit output, BT.2020 primaries/matrix, PQ/HLG transfer, and source mastering-display/MaxCLL/MaxFALL metadata where present.
- Dolby Vision configuration/frame metadata and HDR10+ frame metadata. Encoded video payload hashes match before and after the multitrack remuxes.
- Full video/audio decoding with FFmpeg error detection, including the held oversized AV1 result. Synthetic-video SSIM spans `0.998571–0.999637`. Paired frames were visually inspected.

The 4K HDR10 case preserves `3840x2160`, 10-bit PQ, all 72 frames, mastering-display metadata, MaxCLL `1000`, and MaxFALL `400`.

## Test sources and retained evidence

Synthetic fixtures use FFmpeg test patterns, generated tones, subtitles, chapters, and a text attachment.
Dynamic-HDR sources come from the upstream test repositories:

- [Dolby Vision fixture](https://github.com/quietvoid/dovi_tool/blob/main/assets/hevc_tests/regular.mkv)
- [HDR10+ fixture](https://github.com/quietvoid/hdr10plus_tool/blob/main/assets/hevc_tests/regular.mkv)

Source blob IDs and SHA-256 hashes, original samples, produced files, probes, job reports, and verification JSON remain in the protected maintenance directory.
The disposable test container is stopped after validation.

## Limits

These are isolated fixture tests, not a full-library compatibility guarantee.
No Plex client playback or calibrated HDR display test was performed.
The small Dolby Vision and HDR10+ samples test metadata retention and remuxing, not every profile or commercial title.

## GPU concurrency benchmark

The live queue drained before this benchmark. Only isolated synthetic fixtures
were used. Both tests retain AV1 NVENC P7, full-resolution multipass, VBR,
spatial/temporal AQ, and lookahead 32.

| Input | Total media duration | One worker, two sequential jobs | Two workers, parallel jobs | Throughput gain |
| --- | --- | --- | --- | --- |
| 1080p H.264 | 128 seconds | 15.739 seconds | 15.521 seconds | 1.4% |
| 2160p VP9 | 96 seconds | 45.462 seconds | 42.603 seconds | 6.7% |

Each setting used the same input, frame count, and encoding arguments.
The benchmark discards encoded packets rather than replacing files.
Two GPU workers are now configured in the live node and the persisted Compose
environment. CPU transcode and health-check limits remain unchanged.

The 100% encoder reading measures busy time, not maximum possible throughput.
It is separate from driver limits on concurrent sessions. See the
[NVIDIA utilization definition](https://docs.nvidia.com/deploy/nvidia-smi/index.html)
and [hardware matrix](https://developer.nvidia.com/video-encode-decode-support-matrix).

These short encoding tests exclude Tdarr's scanning, health checks, and file
copies. They do not establish a complete queue speedup. The 1080p difference
is small enough to be timing variation. Encoding quality settings are unchanged.
