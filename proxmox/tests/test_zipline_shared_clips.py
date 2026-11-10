"""Exercise opt-in publication, retries, and revocation without a live Zipline."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "files/zipline/shared-clips.py"
spec = importlib.util.spec_from_file_location("shared_clips", path)
clips = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clips)


class SharedClipsTest(unittest.TestCase):
    def test_container_boxes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"\0\0\0\x08moov\0\0\0\x0cmdat1234")
            self.assertTrue(clips.complete_movie(media, media.stat().st_size))
            media.write_bytes(media.read_bytes()[:-1])
            self.assertFalse(clips.complete_movie(media, media.stat().st_size))
            link = Path(tmp) / "outside.mp4"
            link.symlink_to(media)
            self.assertIsNone(clips.signature(link))

    def test_withdrawal_only_unlinks_managed_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"original")
            uploads = root / "uploads"
            uploads.mkdir()
            (uploads / "renamed.mp4").symlink_to(source)
            unrelated = uploads / "old-name.mp4"
            unrelated.write_bytes(b"unrelated")
            with patch.object(clips, "UPLOADS", uploads), patch.object(clips, "sql", side_effect=["renamed.mp4", ""]):
                clips.remove_entry(source, {"id": "test", "storage": unrelated.name})
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(unrelated.read_bytes(), b"unrelated")
            self.assertFalse((uploads / "renamed.mp4").is_symlink())

    def test_wait_retry_remove_and_reentry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "admin.json").write_text('{"username":"owner"}')
            current = {"My clip.mp4": [10, 1000, 100]}
            with (patch.object(clips, "APP", root), patch.object(clips, "STATE", root / "state"),
                  patch.object(clips, "snapshot", return_value=current),
                  patch.object(clips, "publish", side_effect=[False, True, True]) as publish,
                  patch.object(clips, "remove_entry") as remove, patch.object(clips.time, "time") as clock):
                clock.return_value = 1
                clips.reconcile()
                clock.return_value = 10
                clips.reconcile()
                publish.assert_not_called()
                current["My clip.mp4"] = [10, 1200, 105]
                clock.return_value = 11
                clips.reconcile()
                clock.return_value = 20
                clips.reconcile()
                publish.assert_not_called()
                clock.return_value = 21
                clips.reconcile()
                clips.reconcile()
                clips.reconcile()
                self.assertEqual(publish.call_count, 2)
                first_id = publish.call_args.args[1]["id"]
                current.clear()
                clips.reconcile()
                self.assertEqual(remove.call_args.args[1]["id"], first_id)
                current["My clip.mp4"] = [10, 1000, 100]
                clips.reconcile()
                self.assertEqual(publish.call_count, 2)
                clock.return_value = 250
                clips.reconcile()
                self.assertEqual(publish.call_count, 3)
                self.assertNotEqual(publish.call_args.args[1]["id"], first_id)


if __name__ == "__main__":
    unittest.main()
