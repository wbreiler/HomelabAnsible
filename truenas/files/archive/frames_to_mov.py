#!/usr/bin/env python3
"""Convert one numbered Maya IFF sequence to a ProRes 4444 MOV on Mac or Windows."""

import argparse
from fractions import Fraction
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from read_maya_iff import read


def sequence(folder):
    frames = []
    prefixes = set()
    for path in Path(folder).iterdir():
        if path.is_file() and path.suffix.lower() == '.iff':
            match = re.fullmatch(r'(.*?)(\d+)\.iff', path.name, re.IGNORECASE)
            if not match:
                raise ValueError(f'Frame has no trailing number: {path.name}')
            prefixes.add(match[1])
            frames.append((int(match[2]), path))
    if not frames:
        raise ValueError('No IFF frames in this folder. Select a sequence subfolder.')
    if len(prefixes) != 1:
        raise ValueError('Folder contains multiple sequences. Select one sequence subfolder.')
    frames.sort()
    for previous, current in zip(frames, frames[1:]):
        if current[0] != previous[0] + 1:
            raise ValueError(f'Missing or duplicate frame between {previous[1].name} and {current[1].name}')
    return [path for _, path in frames]


def make_movie(folder, destination, fps, ffmpeg='ffmpeg'):
    rate = Fraction(str(fps))
    if not 0 < rate <= 240:
        raise ValueError('FPS must be greater than zero and at most 240')
    encoder = shutil.which(ffmpeg)
    if encoder is None:
        raise ValueError('FFmpeg not found. Install it or use --ffmpeg /path/to/ffmpeg.')
    destination = Path(destination)
    if destination.suffix.lower() != '.mov':
        raise ValueError('Output must end in .mov')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Output already exists: {destination}')
    frames = sequence(folder)
    spec, pixels = read(frames[0])
    signature = (spec.width, spec.height, spec.nchannels, str(spec.format))
    pixel_format = ('rgba' if spec.nchannels == 4 else 'rgb24')
    if str(spec.format) == 'uint16':
        pixel_format = 'rgba64le' if spec.nchannels == 4 else 'rgb48le'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='iff-mov-', dir=destination.parent) as temporary:
        movie = Path(temporary) / 'movie.mov'
        command = [encoder, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                   '-f', 'rawvideo', '-pixel_format', pixel_format,
                   '-video_size', f'{spec.width}x{spec.height}', '-framerate', str(rate),
                   '-i', 'pipe:0', '-an', '-c:v', 'prores_ks', '-profile:v', '4',
                   '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16', str(movie)]
        with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
            try:
                for index, frame in enumerate(frames):
                    if index:
                        current, pixels = read(frame)
                        if (current.width, current.height, current.nchannels, str(current.format)) != signature:
                            raise ValueError(f'Frame dimensions, channels or depth changed: {frame.name}')
                    process.stdin.write(pixels.astype('<u2' if str(spec.format) == 'uint16' else 'u1',
                                                      copy=False).tobytes())
                    print(f'Frame {index + 1}/{len(frames)}: {frame.name}', flush=True)
                process.stdin.close()
                if process.wait():
                    raise ValueError('FFmpeg failed. See its error above.')
            except BaseException:
                process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                process.wait()
                raise
        os.link(movie, destination)  # Publish only a complete movie, without overwriting.
    return len(frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='Folder containing one numbered IFF sequence')
    parser.add_argument('output', type=Path)
    parser.add_argument('--fps', required=True, help='For example: 24, 25, or 24000/1001')
    parser.add_argument('--ffmpeg', default='ffmpeg', help='FFmpeg executable name or full path')
    args = parser.parse_args()
    try:
        count = make_movie(args.folder, args.output, args.fps, args.ffmpeg)
        print(f'Created {args.output} ({count} frames at {args.fps} FPS)')
    except (OSError, ValueError, ZeroDivisionError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
