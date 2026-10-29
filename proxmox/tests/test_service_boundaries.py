"""Exercise service path boundaries without hosts, downloads, or application code."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("directories", ROOT / "files/service-directories.py")
directories = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directories)


def tasks(path):
    def visit(items):
        for item in items:
            yield item
            for section in ("block", "rescue", "always"):
                yield from visit(item.get(section, []))
    return {item["name"]: item for item in visit(yaml.safe_load((ROOT / path).read_text()))}


def service_script(task):
    argv = task["ansible.builtin.command"]["argv"]
    source = argv[argv.index("-ceu") + 1]
    if "runuser -u" in source:
        child = shlex.split(source)
        source = child[child.index("-ceu") + 1]
    return source


class ServiceBoundaries(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.fd = os.open(self.root, directories.DIRECTORY_FLAGS)
        self.addCleanup(os.close, self.fd)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Preserve Linux mv -T/stat -c semantics when fixtures run on macOS.
        self.executable("mv", "os.replace(sys.argv[-2], sys.argv[-1])")
        self.executable("stat", "print(oct(os.lstat(sys.argv[-1]).st_mode & 0o7777)[2:])")
        self.executable("chmod", "os.chmod(sys.argv[-1], int(sys.argv[1], 8))")
        self.environment = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\nimport json, os, sys\n{source}\n")
        path.chmod(0o755)

    def run_script(self, source, *arguments, content=""):
        return subprocess.run(
            ["/bin/bash", "-ceu", source, "fixture", *map(str, arguments)],
            input=content, text=True, capture_output=True, check=True, env=self.environment,
        ).stdout

    def test_bootstrap_rejects_symlink_leaf_and_ancestor(self):
        victim = self.root / "victim"
        victim.mkdir(mode=0o700)
        (self.root / "link").symlink_to(victim, target_is_directory=True)
        for parts in (("link",), ("link", "child")):
            with self.subTest(parts=parts), self.assertRaises(OSError):
                directories.prepare(self.fd, parts, os.getuid(), os.getgid(), 0o755)
        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o700)
        self.assertFalse((victim / "child").exists())

    def test_bootstrap_rejects_writable_ancestors_and_is_idempotent(self):
        unsafe = self.root / "unsafe"
        unsafe.mkdir()
        unsafe.chmod(0o777)
        with self.assertRaises(PermissionError):
            directories.prepare(self.fd, ("unsafe", "child"), os.getuid(), os.getgid(), 0o755)
        self.assertFalse((unsafe / "child").exists())
        self.assertTrue(directories.prepare(self.fd, ("normal", "app"), os.getuid(), os.getgid(), 0o750))
        self.assertFalse(directories.prepare(self.fd, ("normal", "app"), os.getuid(), os.getgid(), 0o750))

    def test_nested_data_paths_drop_root_before_creation(self):
        service_uid = os.getuid() or 65534
        parent = SimpleNamespace(st_uid=service_uid, st_mode=stat.S_IFDIR | 0o750)
        with patch.object(directories.os, "geteuid", return_value=0), patch.object(directories.os, "fstat", return_value=parent):
            with self.assertRaises(directories.ServiceOwnedParent):
                directories.prepare(self.fd, ("nested", "data"), service_uid, os.getgid(), 0o750)
        self.assertFalse((self.root / "nested").exists())
        data = self.root / "nested" / "data"
        command = [sys.executable, "-c", directories.UNPRIVILEGED_DIRECTORY, str(data), "0750"]
        self.assertEqual(subprocess.check_output(command, text=True), "changed\n")
        (data / "database").write_text("preserved")
        self.assertEqual(subprocess.check_output(command, text=True), "unchanged\n")
        self.assertEqual((data / "database").read_text(), "preserved")
        self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o750)

    def test_version_markers_replace_symlinks_without_touching_targets(self):
        for role, task_name in (
            ("bambuddy", "Install pinned Bambuddy release"),
            ("nexdeck", "Install pinned NexDeck release"),
        ):
            source = service_script(tasks(f"roles/{role}/tasks/main.yml")[task_name])
            source = "marker=$(" + source.split("marker=$(", 1)[1]
            app = self.root / role
            app.mkdir()
            victim = self.root / f"{role}-victim"
            victim.write_text("protected")
            marker = app / ".ansible-version"
            marker.symlink_to(victim)
            if role == "nexdeck":
                source = source.replace("/opt/nexdeck", str(app))
                arguments = ["1.2.3"]
            else:
                source = 'directory="$1"\nversion="$2"\n' + source
                arguments = [app, "1.2.3"]
            self.run_script(source, *arguments)
            self.assertEqual(victim.read_text(), "protected")
            self.assertFalse(marker.is_symlink())
            self.assertEqual(marker.read_text(), "1.2.3\n")
            self.run_script(source, *arguments)
            self.assertEqual(marker.read_text(), "1.2.3\n")

    def test_gatus_binary_and_marker_replace_symlinks(self):
        task = tasks("roles/gatus/tasks/lxc.yml")["Install Gatus binary"]
        app = self.root / "gatus"
        app.mkdir()
        victim = self.root / "victim"
        victim.write_text("protected")
        for filename in ("gatus", ".ansible-version"):
            (app / filename).symlink_to(victim)
        self.run_script(service_script(task), app, "5.0.0", content="verified binary")
        self.assertEqual(victim.read_text(), "protected")
        self.assertEqual((app / "gatus").read_text(), "verified binary")
        self.assertEqual((app / ".ansible-version").read_text(), "5.0.0\n")
        self.assertEqual(stat.S_IMODE((app / "gatus").stat().st_mode), 0o755)

    def test_gatus_configs_replace_symlinks_with_private_files(self):
        for workflow in ("lxc", "guest"):
            task = tasks(f"roles/gatus/tasks/{workflow}.yml")["Install Gatus configuration"]
            self.assertTrue(task["no_log"])
            app = self.root / workflow
            app.mkdir()
            victim = self.root / f"{workflow}-victim"
            victim.write_text("protected")
            config = app / "config.yaml"
            config.symlink_to(victim)
            source = service_script(task)
            self.run_script(source, app, content="webhook: dummy-secret\n")
            self.assertEqual(victim.read_text(), "protected")
            self.assertFalse(config.is_symlink())
            self.assertEqual(config.read_text(), "webhook: dummy-secret\n")
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            if workflow == "guest":
                self.assertEqual(self.run_script(source, app, content=config.read_text()), "")
                config.chmod(0o644)
                self.assertEqual(self.run_script(source, app, content=config.read_text()), "changed\n")
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)

    def test_bambuddy_preserves_existing_environment(self):
        task = tasks("roles/bambuddy/tasks/main.yml")["Initialize Bambuddy environment without replacing local settings"]
        source = service_script(task)
        app = self.root / "bambuddy"
        app.mkdir()
        self.assertEqual(self.run_script(source, app, content="DEFAULT=true\n"), "created\n")
        self.assertEqual((app / ".env").read_text(), "DEFAULT=true\n")
        (app / ".env").write_text("LOCAL=preserved\n")
        self.assertEqual(self.run_script(source, app, content="DEFAULT=true\n"), "")
        self.assertEqual((app / ".env").read_text(), "LOCAL=preserved\n")

    def test_installers_drop_privileges_before_service_tree_operations(self):
        for role, filename, name in (
            ("bambuddy", "main", "Install pinned Bambuddy release"),
            ("nexdeck", "main", "Install pinned NexDeck release"),
            ("gatus", "lxc", "Install Gatus binary"),
            ("gatus", "guest", "Install Gatus binary atomically"),
        ):
            task = tasks(f"roles/{role}/tasks/{filename}.yml")[name]
            argv = task["ansible.builtin.command"]["argv"]
            source = argv[argv.index("-ceu") + 1]
            tokens = shlex.split(source)
            runuser = tokens.index("runuser")
            self.assertEqual(tokens[runuser:runuser + 6], ["runuser", "-u", role, "--", "bash", "-ceu"])
            child = runuser + 6
            root_commands = tokens[:child] + tokens[child + 1:]
            for command in ("tar", "chown", "mkdir", "python3", "npm", "install", "printf"):
                self.assertNotIn(command, root_commands)
            self.assertIn("<", root_commands)

    def test_tree_reads_use_service_accounts_and_arr_uses_stdin(self):
        for role, filename, task_name in (
            ("bambuddy", "main", "Read managed Bambuddy version"),
            ("nexdeck", "main", "Read installed NexDeck version"),
            ("gatus", "lxc", "Read managed Gatus version"),
            ("gatus", "guest", "Read managed Gatus version"),
            ("gatus", "lxc", "Read installed Gatus configuration"),
        ):
            read = tasks(f"roles/{role}/tasks/{filename}.yml")[task_name]
            self.assertFalse(read["check_mode"])
            argv = read["ansible.builtin.command"]["argv"]
            user = argv.index("runuser")
            self.assertEqual(argv[user:user + 6], ["runuser", "-u", role, "--", "cat", argv[-1]])
        record = self.root / "curl.json"
        self.environment["CURL_RECORD"] = str(record)
        self.executable("curl", "open(os.environ['CURL_RECORD'], 'w').write(json.dumps({'argv':sys.argv[1:],'stdin':sys.stdin.read()}))\nprint('{\"version\":\"4.0.1.2\"}')")
        config = self.root / "config.xml"
        config.write_text("<ApiKey>dummy-private-key</ApiKey>\n")
        for role, name in (
            ("sonarr", "Read installed Sonarr version"),
            ("sonarr", "Verify Sonarr application version"),
            ("radarr", "Read installed Radarr version"),
            ("radarr", "Verify Radarr application version"),
        ):
            task = tasks(f"roles/{role}/tasks/main.yml")[name]
            argv = task["ansible.builtin.command"]["argv"]
            output = self.run_script(argv[argv.index("-c") + 1], config, "8989")
            self.assertEqual(output.strip(), "4.0.1.2")
            captured = json.loads(record.read_text())
            self.assertNotIn("dummy-private-key", json.dumps(captured["argv"]))
            self.assertIn("dummy-private-key", captured["stdin"])
            self.assertIn("--header", captured["argv"])
            self.assertNotIn("--config", captured["argv"])
            self.assertTrue(task["no_log"])

    def test_arr_header_bytes_cannot_become_curl_options(self):
        victim = self.root / "victim"
        victim.write_text("protected")
        private = self.root / "private"
        private.write_text("private-file-content")
        response = self.root / "response.json"
        response.write_text('{"version":"4.0.1.2"}')
        config = self.root / "config.xml"
        config.write_text(
            '<ApiKey>dummy"</ApiKey>\n'
            f'<ApiKey>output = "{victim}"</ApiKey>\n'
            f'<ApiKey>url = "{private.as_uri()}"</ApiKey>\n'
            '<ApiKey>header = "X-Extra: end</ApiKey>\n'
        )
        for role, name in (
            ("sonarr", "Read installed Sonarr version"),
            ("sonarr", "Verify Sonarr application version"),
            ("radarr", "Read installed Radarr version"),
            ("radarr", "Verify Radarr application version"),
        ):
            task = tasks(f"roles/{role}/tasks/main.yml")[name]
            argv = task["ansible.builtin.command"]["argv"]
            source = argv[argv.index("-c") + 1]
            # Exercise real curl against a file URL, with no network or user curlrc.
            source = source.replace('http://127.0.0.1:${port}/api/v3/system/status', response.as_uri())
            source = source.replace('curl -fsS', '/usr/bin/curl --disable -fsS')
            self.assertEqual(self.run_script(source, config, "8989"), "4.0.1.2\n")
            self.assertEqual(victim.read_text(), "protected")


if __name__ == "__main__":
    unittest.main()
