#!/usr/bin/env python3
"""Offline import checks. Downloads use fixtures and never contact a server."""

import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pack_archive


class PackArchiveTests(unittest.TestCase):
    def archive(self, files):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)
        data.seek(0)
        return zipfile.ZipFile(data)

    def test_path_escape_and_non_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("../outside", "mods/../../outside", "/etc/example", "mods\\outside", "", None, "mods/./x"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    pack_archive.destination(root, name)
            self.assertEqual(pack_archive.destination(root, "mods/example.jar"), root / "mods/example.jar")

    def test_archive_rejects_links_and_special_files_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
                info = zipfile.ZipInfo("defaultconfigs")
                info.create_system = 3
                info.external_attr = (kind | 0o777) << 16
                with self.archive({"mods/safe.jar": b"safe", info: b"/outside"}) as archive:
                    with self.assertRaises(ValueError):
                        pack_archive.members(archive, root)
                self.assertFalse((root / "mods").exists())

    def test_archive_escape_and_symlinked_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "pack"
            root.mkdir()
            (root / "mods").symlink_to(base, target_is_directory=True)
            for name in ("../outside", "mods/outside"):
                with self.archive({name: b"bad"}) as archive, self.assertRaises(ValueError):
                    pack_archive.members(archive, root)
            self.assertFalse((base / "outside").exists())

    def test_manifest_downloads_and_override_priority(self):
        index = {"dependencies": {"minecraft": "1.21.1", "neoforge": "21.1.1"}, "files": [
            {"path": "mods/example.jar", "downloads": ["https://cdn.example/mod.jar"]},
            {"path": "mods/client.jar", "downloads": ["file:///private"], "env": {"server": "unsupported"}},
        ]}
        files = {"modrinth.index.json": json.dumps(index), "overrides/config/settings": b"first",
                 "server-overrides/config/settings": b"last", "overrides/kubejs/startup_scripts/a.js": b"script"}
        with tempfile.TemporaryDirectory() as directory, self.archive(files) as archive:
            root = Path(directory)

            def download(arguments, check):
                self.assertTrue(check)
                self.assertEqual(arguments[:7], ["curl", "-q", "--proto", "=https", "--proto-redir", "=https", "-fsSL"])
                self.assertEqual(arguments[-2:], ["--", "https://cdn.example/mod.jar"])
                Path(arguments[arguments.index("-o") + 1]).write_bytes(b"downloaded")

            with patch("pack_archive.subprocess.run", side_effect=download) as run:
                pack_archive.assemble(archive, root, pack_archive.members(archive, root))
            self.assertEqual(run.call_count, 1)
            self.assertEqual((root / "mods/example.jar").read_bytes(), b"downloaded")
            self.assertFalse((root / "mods/client.jar").exists())
            self.assertEqual((root / "config/settings").read_bytes(), b"last")
            self.assertEqual((root / "kubejs/startup_scripts/a.js").read_bytes(), b"script")

    def test_all_manifest_paths_and_urls_checked_before_downloads(self):
        for invalid in ({"path": "../sentinel", "downloads": ["https://cdn.example/a"]},
                        {"path": "mods/a.jar", "downloads": ["file:///private"]},
                        {"path": "mods/a.jar", "downloads": ["--config=/private"]},
                        {"path": "mods/a.jar", "downloads": ["http://cdn.example/a"]}):
            index = {"files": [{"path": "mods/safe.jar", "downloads": ["https://cdn.example/a"]}, invalid]}
            with tempfile.TemporaryDirectory() as directory, self.archive({"modrinth.index.json": json.dumps(index)}) as archive:
                root = Path(directory)
                with patch("pack_archive.subprocess.run") as run, self.assertRaises(ValueError):
                    pack_archive.assemble(archive, root, pack_archive.members(archive, root))
                run.assert_not_called()

    def test_rejected_pack_never_connects_to_remote(self):
        script = Path(__file__).with_name("apply-manual-pack.sh")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            ssh = commands / "ssh"
            called = root / "ssh-called"
            ssh.write_text(f"#!/bin/sh\ntouch '{called}'\nexit 99\n")
            ssh.chmod(0o755)
            pack = root / "unsafe.zip"
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("../outside", "bad")
            import os
            result = subprocess.run(["bash", str(script), str(pack), "root@fixture"],
                                    env=dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}"),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(called.exists())
            self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
