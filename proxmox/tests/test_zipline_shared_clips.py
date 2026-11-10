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

    def test_nested_scan_and_folder_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Shared"
            game = root / "Overwatch"
            nested = game / "Player's picks"
            nested.mkdir(parents=True)
            (game / "Empty").mkdir()
            hidden = root / ".staging"
            hidden.mkdir()
            (hidden / "secret.mp4").write_bytes(b"private")
            (root / "shortcut").symlink_to(hidden, target_is_directory=True)
            for folder in (root, game, nested):
                (folder / "round.mp4").write_bytes(b"video")
            files, folders = clips.scan_tree(root)
            self.assertEqual(set(files), {"round.mp4", "Overwatch/round.mp4", "Overwatch/Player's picks/round.mp4"})
            self.assertEqual(folders, ["Overwatch", "Overwatch/Empty", "Overwatch/Player's picks"])
            root_id = "a" * 32
            relative = nested.relative_to(root)
            game_id = clips.folder_id(root_id, relative.parent)
            self.assertEqual(clips.folder_id(root_id, Path(".")), root_id)
            inserts = clips.folder_inserts(root_id, [relative, *relative.parents], "'owner'")
            self.assertIn(f"'Overwatch','owner','{root_id}'", inserts)
            self.assertIn(f"'Player''s picks','owner','{game_id}'", inserts)

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

    def test_preview_readiness_and_dashboard_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "admin.json").write_text('{"username":"owner"}')
            current = {"Nested/Silent.webm": [20, 1000, 50]}
            with (patch.object(clips, "APP", root), patch.object(clips, "STATE", root / "state"),
                  patch.object(clips, "snapshot", return_value=(current, ["Nested"])),
                  patch.object(clips, "sql", return_value="owner-id"),
                  patch.object(clips, "ready_previews", return_value=set()) as ready,
                  patch.object(clips, "publish", return_value=True) as publish,
                  patch.object(clips.time, "time") as clock):
                clock.return_value = 1
                clips.reconcile()
                clock.return_value = 15
                clips.reconcile()
                publish.assert_not_called()
                state = clips.json.loads(clips.STATE.read_text())
                entry = state["files"]["Nested/Silent.webm"]
                manifest = root / "preview-catalog/clips.json"
                self.assertEqual(clips.json.loads(manifest.read_text()),
                                 {entry["storage"]: "Nested/Silent.webm"})
                ready.return_value = {entry["storage"].rsplit(".", 1)[0] + ".mp4"}
                clips.reconcile()
                publish.assert_called_once()
                # Dashboard deletion removes the encoding request while preserving the source.
                clips.reconcile()
                self.assertEqual(clips.json.loads(manifest.read_text()), {})
                self.assertTrue(clips.json.loads(clips.STATE.read_text())["files"]["Nested/Silent.webm"]["published"])

    def test_wait_retry_remove_and_reentry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "admin.json").write_text('{"username":"owner"}')
            current = {"My clip.mp4": [10, 1000, 100]}
            with (patch.object(clips, "APP", root), patch.object(clips, "STATE", root / "state"),
                  patch.object(clips, "snapshot", return_value=(current, [])), patch.object(clips, "sql", return_value="owner-id"),
                  patch.object(clips, "ready_previews", side_effect=lambda: {
                      entry["storage"].rsplit(".", 1)[0] + ".mp4" for entry in
                      clips.json.loads(clips.STATE.read_text())["files"].values() if "storage" in entry}),
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
