import ast
from pathlib import Path
import shlex
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check_migration_source


class MigrationSourceTests(unittest.TestCase):
    def metadata(self, path):
        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=1000 if str(path) == "/opt/minecraft" else 0)

    def test_service_owned_source_under_protected_parents_is_valid(self):
        with patch("pathlib.Path.lstat", autospec=True, side_effect=self.metadata):
            check_migration_source.validate_source("/opt/minecraft/")

    def test_relative_root_and_parent_escape_are_rejected(self):
        for source in ("relative", "/", "/opt/../etc"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_migration_source.validate_source(source)

    def test_source_link_and_unsafe_ancestors_are_rejected(self):
        for unsafe_path, mode, uid in (("/opt/minecraft", stat.S_IFLNK | 0o777, 1000),
                                      ("/opt", stat.S_IFLNK | 0o777, 0),
                                      ("/opt", stat.S_IFDIR | 0o755, 1000),
                                      ("/opt", stat.S_IFDIR | 0o775, 0),
                                      ("/", stat.S_IFDIR | 0o757, 0)):
            def metadata(path):
                return SimpleNamespace(st_mode=mode, st_uid=uid) if str(path) == unsafe_path else self.metadata(path)

            with self.subTest(path=unsafe_path, mode=mode, uid=uid), patch("pathlib.Path.lstat", metadata):
                with self.assertRaises(ValueError):
                    check_migration_source.validate_source("/opt/minecraft")

    def test_rsync_preserves_links_and_verifies_the_second_hop(self):
        role = Path(__file__).parents[1] / "ansible/roles/minecraft_server/tasks/main.yml"
        task = role.read_text().split("- name: Migrate server data directly from source to new server", 1)[1]
        arguments = []
        for line in task.split("  delegate_to:", 1)[0].splitlines():
            if line.startswith("      - "):
                value = line.strip()[2:]
                arguments.append(ast.literal_eval(value) if value.startswith('"') else value)
        self.assertEqual(arguments[0], "rsync")
        self.assertIn("-az", arguments)
        self.assertFalse(any(value in arguments for value in ("-L", "-k", "--copy-links", "--copy-dirlinks", "--copy-unsafe-links")))
        transport = shlex.split(next(value.removeprefix("--rsh=") for value in arguments if value.startswith("--rsh=")))
        self.assertEqual(transport[0], "ssh")
        self.assertIn("StrictHostKeyChecking=accept-new", transport)
        self.assertNotIn("-A", transport)
        self.assertIn("-a", transport)
        self.assertFalse(any("UserKnownHostsFile=" in value or value == "StrictHostKeyChecking=no" for value in transport))
        self.assertIn("--rsync-path=runuser -u minecraft -- rsync", arguments)


if __name__ == "__main__":
    unittest.main()
