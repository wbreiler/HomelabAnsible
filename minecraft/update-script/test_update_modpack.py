#!/usr/bin/env python3
"""Exercise updater transactions offline with recorded privilege boundaries."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


STUB = r'''
import json, os, pathlib, shutil, subprocess, sys, tempfile
command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
base = pathlib.Path(os.environ["TEST_ROOT"])
game = (base / "game").resolve()
service = os.environ.get("TEST_MINECRAFT") == "1"
with (base / "commands.jsonl").open("a") as stream:
    stream.write(json.dumps([command, service, args]) + "\n")
if command == "runuser":
    assert args[:3] == ["-u", "minecraft", "--"]
    assert "CURSEFORGE_API_KEY" not in os.environ
    assert "DISCORD_WEBHOOK_URL" not in os.environ
    sys.exit(subprocess.run(args[3:], env=dict(os.environ, TEST_MINECRAFT="1")).returncode)
elif command == "curl":
    assert args[:6] == ["-q", "--proto", "=https", "--proto-redir", "=https", "-fsSL"]
    assert not any("fake-secret" in value for value in args)
    config = sys.stdin.read() if "--config" in args else ""
    if "--" not in args:
        assert 'url = "https://discord.example/fake-secret' in config
        sys.exit(0)
    url = args[-1]
    if not url.startswith("https://"):
        sys.exit(1)
    if url.startswith("https://api.curseforge.com/"):
        assert 'header = "x-api-key: fake-secret' in config
        if url.endswith("download-url"):
            print(json.dumps({"data": "https://cdn.example/new.jar" if "/files/12/" in url else "https://cdn.example/pack.zip"}))
        else:
            print(json.dumps({"data": [{"id": 2, "displayName": "new pack", "releaseType": 1,
                                      "fileDate": "2026-01-01", "serverPackFileId": None if os.environ.get("TEST_CF_MANIFEST") else 3,
                                      "downloadUrl": "https://cdn.example/pack.zip"}]}))
    elif url.startswith("https://api.modrinth.com/"):
        print(json.dumps([{"id": "2", "name": "new pack", "version_type": "release",
                           "date_published": "2026-01-01", "files": [{"primary": True, "url": "https://cdn.example/pack.zip"}]}]))
    elif url.endswith("installer.jar"):
        assert not service
        pathlib.Path(args[args.index("-o") + 1]).write_bytes(b"installer")
    else:
        target = pathlib.Path(args[args.index("-o") + 1])
        if url.endswith("pack.zip"):
            assert not service
            shutil.copyfile(base / "pack.zip", target)
        else:
            assert service
            target.write_bytes(b"new mod")
elif command == "systemctl":
    assert not service
    state = base / "state"
    if args[0] == "is-active":
        sys.exit(0 if state.read_text() == "running" else 1)
    if args[0] == "stop":
        state.write_text("stopped")
    elif args[0] in ("start", "restart"):
        failures = base / "start-failed"
        if os.environ.get("TEST_FAIL_START") and not failures.exists():
            failures.touch()
            sys.exit(1)
        state.write_text("running")
elif command == "mktemp":
    template = args[-1]
    assert service or template.startswith("/var/tmp/minecraft-update.") or "minecraft-update." in pathlib.Path(template).parent.name
    parent = pathlib.Path(template).parent if pathlib.Path(template).parent.is_relative_to(base) else base
    prefix = pathlib.Path(template).name.replace("XXXXXX", "")
    if "-d" in args:
        name = tempfile.mkdtemp(prefix=prefix, dir=parent)
    else:
        suffix = next((value.split("=", 1)[1] for value in args if value.startswith("--suffix=")), "")
        descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=parent)
        os.close(descriptor)
    print(name)
elif command == "chgrp":
    assert not service and args[0] == "minecraft"
    assert not pathlib.Path(args[-1]).is_relative_to(game)
elif command == "mv":
    assert service and args[:2] == ["-T", "--"]
    os.rename(args[-2], args[-1])
elif command == "cp":
    assert service
    source, target = map(pathlib.Path, args[-2:])
    if "--remove-destination" in args and target.is_symlink():
        target.unlink()
    if source.is_dir():
        if not args[-2].endswith("/."):
            target = target / source.name
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copyfile(source, target)
elif command == "cat":
    assert service
    target = pathlib.Path(args[-1]).resolve()
    if not target.is_relative_to(game):
        sys.exit(1)
    sys.stdout.write(target.read_text())
elif command == "find":
    assert service
    root = pathlib.Path(args[0])
    if "-printf" in args:
        for path in root.glob("mods.bak.*"):
            if path.is_dir():
                print(f"{path.stat().st_mtime} {path}")
    elif "-print" in args:
        for path in root.iterdir():
            if path.name != "mods":
                print(path)
    else:
        mode = 0o755 if args[args.index("-type") + 1] == "d" else 0o644
        for path in [root, *root.rglob("*")]:
            if not path.is_symlink() and (path.is_dir() if mode == 0o755 else path.is_file()):
                path.chmod(mode)
elif command == "java":
    assert service and args[0] == "-jar" and args[-1] == "--installServer"
    assert "minecraft-update." in pathlib.Path(args[1]).parent.name
    (game / "run.sh").write_text("#!/bin/sh\nexit 0\n")
else:
    raise AssertionError(command)
'''


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        (self.game / "mods").mkdir(parents=True)
        (self.game / "mods/old.jar").write_bytes(b"old mod")
        (self.game / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.game / ".current_version").write_text("1\n")
        (self.game / ".running_version").write_text("1\n")
        (self.root / "state").write_text("running")
        commands = self.root / "bin"
        commands.mkdir()
        for command in ("runuser", "curl", "systemctl", "mktemp", "chgrp", "mv", "cp", "cat", "find", "java"):
            executable = commands / command
            executable.write_text(f"#!{sys.executable}\n" + STUB)
            executable.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}",
                        TEST_ROOT=str(self.root), LOG_FILE=str(self.root / "update.log"),
                        CURSEFORGE_API_KEY="inherited-secret", DISCORD_WEBHOOK_URL="inherited-secret")

    def run_update(self, source="curseforge", fail_start=False):
        config = self.root / "update.conf"
        config.write_text(f'''PACK_SOURCE="{source}"
PACK_NAME="fixture"
INSTANCE_NAME="fixture"
MC_VERSION="1.21.1"
LOADER="neoforge"
MINECRAFT_DIR="{self.game}"
MODPACK_SLUG="fixture"
CURSEFORGE_PROJECT_ID="1"
CURSEFORGE_API_KEY='fake-secret-$2a$10$-key'
DISCORD_WEBHOOK_URL='https://discord.example/fake-secret-webhook'
SERVICE_VERIFY_DELAY=0
''')
        script = Path(__file__).with_name("update-modpack.sh")
        env = dict(self.env, TEST_FAIL_START="1") if fail_start else self.env
        return subprocess.run([shutil.which("bash"), str(script), "--no-wait", "--config", str(config)],
                              env=env, capture_output=True, text=True)

    def pack(self, files):
        with zipfile.ZipFile(self.root / "pack.zip", "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def test_server_pack_replaces_launcher_links_without_touching_sentinel(self):
        sentinel = self.root / "private"
        sentinel.write_bytes(b"private data")
        (self.game / "run.sh").unlink()
        (self.game / "run.sh").symlink_to(sentinel)
        (self.game / "run.bat").symlink_to(sentinel)
        self.pack({"mods/new.jar": b"new mod", "run.sh": b"#!/bin/sh\nexit 0\n",
                   "run.bat": b"exit 0\n", "libraries/loader.jar": b"loader"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(sentinel.read_bytes(), b"private data")
        self.assertFalse((self.game / "run.sh").is_symlink())
        self.assertEqual((self.game / "mods/new.jar").read_bytes(), b"new mod")
        self.assertEqual((self.game / ".current_version").read_text(), "2\n")
        self.assertEqual((self.game / ".running_version").read_text(), "2\n")
        self.assertEqual(len(list(self.game.glob("mods.bak.*"))), 1)
        self.assertEqual((self.root / "state").read_text(), "running")
        records = [json.loads(line) for line in (self.root / "commands.jsonl").read_text().splitlines()]
        self.assertTrue(all(service for command, service, _ in records if command in ("cat", "mv", "find")))
        self.assertNotIn("fake-secret", (self.root / "update.log").read_text())

    def test_marker_link_cannot_disclose_private_data(self):
        sentinel = self.root / "private"
        sentinel.write_text("private marker sentinel")
        (self.game / ".current_version").unlink()
        (self.game / ".current_version").symlink_to(sentinel)
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("private marker sentinel", result.stdout + result.stderr)
        self.assertNotIn("private marker sentinel", (self.root / "update.log").read_text())
        self.assertEqual((self.root / "state").read_text(), "running")

    def test_failed_start_restores_old_mods(self):
        self.pack({"mods/new.jar": b"new mod", "run.sh": b"#!/bin/sh\nexit 0\n"})
        result = self.run_update(fail_start=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Rolling back mod directory", result.stdout)
        self.assertEqual((self.game / "mods/old.jar").read_bytes(), b"old mod")
        self.assertFalse((self.game / "mods/new.jar").exists())
        self.assertEqual((self.game / ".current_version").read_text(), "1\n")
        self.assertEqual((self.root / "state").read_text(), "running")

    def test_file_url_failure_does_not_stop_service(self):
        index = {"files": [{"path": "mods/secret.jar", "downloads": ["file:///root/private"]}]}
        self.pack({"modrinth.index.json": json.dumps(index)})
        result = self.run_update(source="modrinth")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required mod secret.jar failed to download", result.stdout)
        self.assertEqual((self.game / "mods/old.jar").read_bytes(), b"old mod")
        self.assertEqual((self.root / "state").read_text(), "running")

    def test_loader_installer_runs_as_service_from_private_stage(self):
        (self.game / "run.sh").unlink()
        index = {"dependencies": {"neoforge": "21.1.1"},
                 "files": [{"path": "mods/new.jar", "downloads": ["https://cdn.example/new.jar"]}]}
        self.pack({"modrinth.index.json": json.dumps(index)})
        result = self.run_update(source="modrinth")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.game / "mods/new.jar").read_bytes(), b"new mod")
        self.assertTrue(os.access(self.game / "run.sh", os.X_OK))
        records = [json.loads(line) for line in (self.root / "commands.jsonl").read_text().splitlines()]
        self.assertTrue(any(command == "java" and service for command, service, _ in records))

    def test_stopped_server_stays_stopped(self):
        (self.root / "state").write_text("stopped")
        self.pack({"mods/new.jar": b"new mod", "run.sh": b"#!/bin/sh\nexit 0\n"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.root / "state").read_text(), "stopped")
        self.assertFalse((self.game / ".running_version").exists())

    def test_curseforge_manifest_installs_mods_and_config_overrides(self):
        self.env["TEST_CF_MANIFEST"] = "1"
        manifest = {"files": [{"projectID": 11, "fileID": 12, "required": True}]}
        self.pack({"manifest.json": json.dumps(manifest), "overrides/config/settings": b"new config"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.game / "mods/new.jar").read_bytes(), b"new mod")
        self.assertEqual((self.game / "config/settings").read_bytes(), b"new config")
        self.assertEqual((self.game / ".current_version").read_text(), "2\n")

    def test_curseforge_manifest_rejects_non_numeric_project_ids(self):
        self.env["TEST_CF_MANIFEST"] = "1"
        manifest = {"files": [{"projectID": "$(unexpected)", "fileID": 12, "required": True}]}
        self.pack({"manifest.json": json.dumps(manifest)})
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest project/file IDs must be numeric", result.stdout)
        self.assertEqual((self.game / "mods/old.jar").read_bytes(), b"old mod")
        self.assertEqual((self.root / "state").read_text(), "running")


if __name__ == "__main__":
    unittest.main()
