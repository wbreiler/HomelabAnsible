# Maya IFF frames to MOV — Mac and Windows

These scripts read Autodesk Maya `FOR4/CIMG` IFF images. They do not read
Amiga ILBM files, Flash projects, or reconstruct a scene from separate passes.
The Gumball frames inspected here contain tiled, RLE-compressed RGB/alpha
channels at 2120 × 1280, with either 8-bit or 16-bit samples.

## Install on your computer

Use Python 3.11 or newer and FFmpeg with the `prores_ks` encoder.
[OpenImageIO](https://pypi.org/project/OpenImageIO/3.1.18.1/) provides Mac and
Windows wheels. [FFmpeg's download page](https://ffmpeg.org/download.html)
links to Mac and Windows builds. These are computer dependencies. Do not
install them on the TrueNAS appliance.

Extract the script bundle into one folder. Keep `frames_to_mov.py` and
`read_maya_iff.py` together. Run the commands below from that folder.

### Mac — Terminal

```sh
python3 -m venv .venv
.venv/bin/python -m pip install OpenImageIO==3.1.18.1 numpy
# If FFmpeg is absent and Homebrew is installed:
brew install ffmpeg
.venv/bin/python frames_to_mov.py "/Volumes/Archive/path/to/NEW_GAY_BTY" "$HOME/Desktop/Gumball.mov" --fps 25
```

### Windows — PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install OpenImageIO==3.1.18.1 numpy
.\.venv\Scripts\python.exe frames_to_mov.py "Z:\path\to\NEW_GAY_BTY" "$env:USERPROFILE\Desktop\Gumball.mov" --fps 25 --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe"
```

Replace the example input with the actual sequence folder. A mapped drive
or UNC share path works on Windows. If FFmpeg is on PATH, omit `--ffmpeg`.
Use the actual production frame rate. **25 is an example, not a verified
frame rate for these files.** Fractional rates such as `24000/1001` work.

## Behavior and limits

- Select one folder containing one numbered sequence, such as
  `shot_0001.iff`, `shot_0002.iff`. The script sorts frame numbers numerically.
  It rejects gaps, duplicate numbers, and multiple sequence names.
- The output is a silent ProRes 4444 `.mov` with transparency. It is suitable
  for editing and composition. Some ordinary video players do not show alpha.
- ProRes compresses color with loss and reduces color precision to the
  encoder's 10-bit format. The output is not a lossless archive of 16-bit
  source frames. Source files remain untouched.
- Frames stream directly to FFmpeg. Only one temporary movie is created,
  beside the requested output. Allow space for a large ProRes file.
  An existing output is never overwritten. Failures remove the temporary movie.
  The destination filesystem must support hard links, such as local APFS or
  NTFS. Export to a local disk, then copy the movie to a share if needed.
- Render passes are exported separately. No color/gamma correction,
  alpha unpremultiplication, pass composition, audio, or frame interpolation
  is applied. Use a compositor for the final shot.

## Inspect or export one image

```sh
python read_maya_iff.py frame.iff --info
python read_maya_iff.py frame.iff frame.png
```

The PNG reader retains the original 8/16-bit channel values. It disables
implicit alpha arithmetic. It limits each decoded image to 128 MiB and
dimensions to 8192 × 8192. The optional repository-local runtime under
`truenas/artifacts/maya-iff-runtime` is ignored by Git.

## Validation

```sh
python -m unittest discover -s . -p 'test_*.py'
```

Independent Maya IFF fixtures cover compressed/uncompressed RGB/RGBA,
8/16-bit samples, orientation, channel order, and exact PNG round trips.
Movie tests use real FFmpeg and FFprobe for frame counts, fractional frame
rate, dimensions, codec, transparency, overwrite refusal, and failure cleanup.
Movie tests skip if the FFmpeg tools are absent.

References: [OpenImageIO IFF reader](https://github.com/AcademySoftwareFoundation/OpenImageIO/blob/main/src/iff.imageio/iffinput.cpp),
[FFmpeg rawvideo input](https://ffmpeg.org/ffmpeg-formats.html#rawvideo),
[FFmpeg ProRes encoder](https://ffmpeg.org/ffmpeg-all.html#ProRes).
