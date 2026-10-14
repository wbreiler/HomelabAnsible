#!/usr/bin/env python3
"""Read Maya FOR4/CIMG images and export channel-preserving PNGs."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

# The optional runtime is local/ignored, never installed into TrueNAS.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'artifacts/maya-iff-runtime'))
try:
    import OpenImageIO as oiio
except ImportError as error:
    raise SystemExit('OpenImageIO is required. See files/archive/README.md.') from error


def read(source):
    source = Path(source)
    with source.open('rb') as stream:
        header = stream.read(12)
    if header[:4] != b'FOR4' or header[8:12] != b'CIMG':
        raise ValueError('Expected Maya FOR4/CIMG image data')
    reader = oiio.ImageInput.open(str(source))
    if reader is None:
        raise ValueError(oiio.geterror())
    try:
        spec = reader.spec()
        if spec.nchannels not in (3, 4) or str(spec.format) not in ('uint8', 'uint16'):
            raise ValueError('This PNG converter supports only 8/16-bit RGB or RGBA')
        if not (0 < spec.width <= 8192 and 0 < spec.height <= 8192):
            raise ValueError('Image dimensions exceed the converter limit')
        if spec.width * spec.height * spec.nchannels * spec.format.size() > 128 * 1024**2:
            raise ValueError('Decoded image exceeds the 128 MiB limit')
        pixels = reader.read_image(format=spec.format)
        if pixels is None:
            raise ValueError(reader.geterror())
        return spec, pixels
    finally:
        reader.close()


def convert(source, destination):
    destination = Path(destination)
    if destination.suffix.lower() != '.png':
        raise ValueError('Output must have a .png extension')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Output already exists: {destination}')
    spec, pixels = read(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.png', dir=destination.parent)
    os.close(fd)
    output = None
    try:
        output = oiio.ImageOutput.create(temporary)
        if output is None:
            raise ValueError(oiio.geterror())
        png_spec = oiio.ImageSpec(spec.width, spec.height, spec.nchannels, spec.format)
        # Skip implicit alpha arithmetic so render/data channels retain their values.
        png_spec.attribute('oiio:UnassociatedAlpha', 1)
        if not output.open(temporary, png_spec) or not output.write_image(pixels):
            raise ValueError(output.geterror())
        if not output.close():
            raise ValueError(output.geterror())
        output = None
        os.link(temporary, destination)  # Fail atomically if another file appeared.
    finally:
        if output is not None:
            output.close()
        Path(temporary).unlink(missing_ok=True)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', nargs='?', type=Path)
    parser.add_argument('--info', action='store_true', help='Decode and print image metadata')
    args = parser.parse_args()
    try:
        if args.info:
            spec, _ = read(args.source)
        else:
            spec = convert(args.source, args.output or args.source.with_suffix('.png'))
        print(json.dumps({'width': spec.width, 'height': spec.height,
                          'channels': spec.nchannels, 'sample_type': str(spec.format),
                          'tile_width': spec.tile_width, 'tile_height': spec.tile_height}))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
