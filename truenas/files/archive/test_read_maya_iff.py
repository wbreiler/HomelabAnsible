"""Exercise channel order, depth, alpha preservation and non-destructive output."""

from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
from read_maya_iff import convert, read, oiio


def chunk(tag, payload):
    return tag + struct.pack('>I', len(payload)) + payload + bytes((-len(payload)) % 4)


def rle(plane):
    result = bytearray()
    i = 0
    while i < len(plane):
        run = 1
        while i + run < len(plane) and plane[i + run] == plane[i] and run < 128:
            run += 1
        if run >= 2:
            result.extend((0x80 | (run - 1), plane[i]))
            i += run
        else:
            start = i
            i += 1
            while i < len(plane) and i - start < 128:
                if i + 1 < len(plane) and plane[i] == plane[i + 1]:
                    break
                i += 1
            result.append(i - start - 1)
            result.extend(plane[start:i])
    return bytes(result)


def fixture(pixels, compressed):
    height, width, channels = pixels.shape
    bits = pixels.dtype.itemsize * 8
    header = struct.pack('>IIHHIHHI', width, height, 1, 1,
                         1 | (2 if channels == 4 else 0), bits // 8 - 1, 1,
                         int(compressed))
    bottom_up = pixels[::-1]
    if compressed:
        # Byte planes: MSBs first, then LSBs, with channels in A/B/G/R order.
        payload = b''.join(rle(((bottom_up[:, :, c] >> shift) & 255)
                              .astype(np.uint8).tobytes())
                           for shift in range(bits - 8, -1, -8)
                           for c in range(channels - 1, -1, -1))
        assert len(payload) < pixels.nbytes
    else:
        payload = bottom_up[:, :, ::-1].astype('>u2' if bits == 16 else 'u1').tobytes()
    tile = chunk(b'RGBA', struct.pack('>HHHH', 0, 0, width - 1, height - 1) + payload)
    return chunk(b'FOR4', b'CIMG' + chunk(b'TBHD', header)
                 + chunk(b'FOR4', b'TBMP' + tile))


class MayaIffTests(unittest.TestCase):
    def test_rgb_and_rgba_at_both_depths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dtype, fmt in [(np.uint8, oiio.UINT8), (np.uint16, oiio.UINT16)]:
                for channels in (3, 4):
                    with self.subTest(dtype=dtype, channels=channels):
                        maximum = np.iinfo(dtype).max
                        pixels = np.zeros((3, 4, channels), dtype=dtype)
                        pixels[:, :, :3] = np.array([0x12, 0x56, 0x9a]) * (257 if dtype == np.uint16 else 1)
                        if channels == 4:
                            pixels[:, :, 3] = maximum // 2
                        pixels[0, 0, :3] = [1, 2, 3]
                        source = root / f'{dtype.__name__}-{channels}.iff'
                        target = source.with_suffix('.png')
                        source.write_bytes(fixture(pixels, compressed=True))
                        _, actual = read(source)
                        np.testing.assert_array_equal(actual, pixels)
                        convert(source, target)
                        config = oiio.ImageSpec()
                        config.attribute('oiio:UnassociatedAlpha', 1)
                        reader = oiio.ImageInput.open(str(target), config)
                        result = reader.read_image(format=reader.spec().format)
                        reader.close()
                        self.assertEqual(result.dtype, pixels.dtype)
                        np.testing.assert_array_equal(result, pixels)
                        before = target.read_bytes()
                        with self.assertRaises(FileExistsError):
                            convert(source, target)
                        self.assertEqual(before, target.read_bytes())


    def test_uncompressed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'raw.iff'
            for dtype in (np.uint8, np.uint16):
                for channels in (3, 4):
                    with self.subTest(dtype=dtype, channels=channels):
                        pixels = (np.arange(2 * 3 * channels).reshape(2, 3, channels) * 101).astype(dtype)
                        source.write_bytes(fixture(pixels, compressed=False))
                        _, actual = read(source)
                        np.testing.assert_array_equal(actual, pixels)

    def test_wrong_format_and_truncated_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for contents in (b'FORM\0\0\0\4ILBM', b'FOR4\0\0\0\4CIMG'):
                source = root / 'broken.iff'
                source.write_bytes(contents)
                with self.assertRaises(ValueError):
                    read(source)
                self.assertFalse(source.with_suffix('.png').exists())


if __name__ == '__main__':
    unittest.main()
