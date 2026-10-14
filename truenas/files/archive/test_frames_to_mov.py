"""Verify sequence validation and a real FFmpeg encode."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from frames_to_mov import make_movie, sequence
from test_read_maya_iff import fixture


class MovieTests(unittest.TestCase):
    def test_sequence_rejects_gaps_duplicates_and_mixed_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for names in [('shot_1.iff', 'shot_3.iff'),
                          ('shot_1.iff', 'shot_01.iff'),
                          ('shot_1.iff', 'other_2.iff')]:
                for name in names:
                    (root / name).touch()
                with self.assertRaises(ValueError):
                    sequence(root)
                for path in root.iterdir():
                    path.unlink()
            for name in ('shot_10.iff', 'shot_9.iff'):
                (root / name).touch()
            self.assertEqual([p.name for p in sequence(root)], ['shot_9.iff', 'shot_10.iff'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_actual_movie_and_failed_output_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = root / 'frames'
            frames.mkdir()
            for dtype in (np.uint8, np.uint16):
                pixels = np.zeros((16, 16, 4), dtype=dtype)
                pixels[:, :, 0] = np.iinfo(dtype).max
                pixels[:, :, 3] = np.iinfo(dtype).max // 2
                for number in range(1, 4):
                    (frames / f'shot_{number}.iff').write_bytes(fixture(pixels, False))
                output = root / f'{dtype.__name__}.mov'
                self.assertEqual(make_movie(frames, output, '24000/1001'), 3)
                result = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                   '-of', 'json', str(output)])
                stream = json.loads(result)['streams'][0]
                self.assertEqual(stream['codec_name'], 'prores')
                self.assertEqual(stream['nb_frames'], '3')
                self.assertEqual(stream['r_frame_rate'], '24000/1001')
                self.assertEqual((stream['width'], stream['height']), (16, 16))
                self.assertTrue(stream['pix_fmt'].startswith('yuva'))
                decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output),
                                                    '-frames:v', '1', '-f', 'rawvideo',
                                                    '-pix_fmt', 'rgba', 'pipe:1'])
                alpha = np.frombuffer(decoded, dtype=np.uint8).reshape(16, 16, 4)[:, :, 3]
                self.assertTrue(np.all((alpha >= 126) & (alpha <= 129)))
                before = output.read_bytes()
                with self.assertRaises(FileExistsError):
                    make_movie(frames, output, 24)
                self.assertEqual(output.read_bytes(), before)
            (frames / 'shot_3.iff').write_bytes(b'broken')
            with self.assertRaises(ValueError):
                make_movie(frames, root / 'failed.mov', 24)
            self.assertFalse((root / 'failed.mov').exists())
            self.assertFalse(list(root.glob('iff-mov-*')))


if __name__ == '__main__':
    unittest.main()
