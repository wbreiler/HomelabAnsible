#!/usr/bin/env python3
"""Exercise manual ZIP deployment locally, without SSH or a Minecraft server."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    script = Path(__file__).with_name("apply-manual-pack.sh")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        commands = root / "bin"
        commands.mkdir()
        stub = f"#!{sys.executable}\n" + '''
import os, pathlib, shutil, subprocess, sys
command = pathlib.Path(sys.argv[0]).name
remote = os.environ["TEST_REMOTE"]
if command == "ssh":
    assert sys.argv[1] == "root@fixture"
    subprocess.run(["bash", "-eu", "-c", sys.argv[2].replace("/opt/minecraft", remote)], check=True)
elif command == "rsync":
    source, destination = sys.argv[-2:]
    assert destination.startswith("root@fixture:/opt/minecraft/")
    destination = destination.split(":", 1)[1].replace("/opt/minecraft", remote)
    shutil.copytree(source, destination, dirs_exist_ok=True)
elif command == "systemctl" and sys.argv[1] == "list-units":
    print("minecraft@fixture.service loaded active running")
elif command not in ("systemctl", "chown"):
    raise AssertionError(command)
'''
        for command in ("ssh", "rsync", "systemctl", "chown"):
            executable = commands / command
            executable.write_text(stub)
            executable.chmod(0o755)

        for with_kubejs in (True, False):
            remote = root / str(with_kubejs)
            (remote / "kubejs/server_scripts").mkdir(parents=True)
            (remote / "kubejs/server_scripts/stale.js").write_text("old script")
            (remote / "world").mkdir()
            (remote / "world/level.dat").write_bytes(b"keep world")
            files = {"mods/example.jar": b"mod", "datapacks/example.zip": b"datapack"}
            if with_kubejs:
                for folder in ("server_scripts", "startup_scripts", "data", "assets", "config"):
                    files[f"kubejs/{folder}/example.txt"] = folder.encode()
            pack = root / "pack.zip"
            with zipfile.ZipFile(pack, "w") as archive:
                for name, contents in files.items():
                    archive.writestr(name, contents)
            env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}", TEST_REMOTE=str(remote))
            result = subprocess.run(["bash", str(script), str(pack), "root@fixture"],
                                    env=env, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            for name, contents in files.items():
                target = remote / ("world/" + name if name.startswith("datapacks/") else name)
                assert target.read_bytes() == contents, name
            backups = list(remote.glob("kubejs.pre-zip-recreate.*"))
            assert len(backups) == 1
            assert (backups[0] / "server_scripts/stale.js").read_text() == "old script"
            assert not (remote / "kubejs/server_scripts/stale.js").exists()
            assert (remote / "world/level.dat").read_bytes() == b"keep world"
    print("PASS: KubeJS deployment, backup, stale-script removal, optional directory, world preservation")


if __name__ == "__main__":
    main()
