"""Check Loki listener privacy, ingress policy, and isolated retention ports."""
import ast
from pathlib import Path
import re
import unittest

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/centralized_logging"


class LoggingIngress(unittest.TestCase):
    def setUp(self):
        self.environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        self.environment.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
        self.environment.filters["type_debug"] = lambda value: type(value).__name__
        self.settings = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.settings.update(centralized_logging_ip="192.0.2.50", centralized_logging_ingest_cidrs=["192.0.2.10/32", "192.0.2.11/32"])

    def render(self, name):
        return self.environment.from_string((ROLE / "templates" / name).read_text()).render(self.settings)

    def test_policy_requires_reviewed_individual_ipv4_sources(self):
        validation = yaml.safe_load((ROLE / "tasks/main.yml").read_text())[0]["ansible.builtin.assert"]["that"]
        expressions = [self.environment.compile_expression(value) for value in validation if "centralized_logging_ingest_cidrs" in value]
        self.assertEqual(len(expressions), 3)
        for value, allowed in (
            (["192.0.2.10/32", "10.10.30.9/32"], True),
            ([], False),
            ("192.0.2.10/32", False),
            ({"192.0.2.10/32": True}, False),
            (["10.0.0.0/8"], False),
            (["999.0.0.1/32"], False),
            (["::/0"], False),
            (["192.0.2.10/32; allow all"], False),
        ):
            with self.subTest(value=value):
                self.assertEqual(all(expression(centralized_logging_ingest_cidrs=value) for expression in expressions), allowed)

    def test_loki_query_and_grpc_listeners_stay_on_loopback(self):
        config = yaml.safe_load(self.render("loki.yml.j2"))
        server = config["server"]
        self.assertEqual(server, {
            "http_listen_address": "127.0.0.1", "http_listen_port": 3101,
            "grpc_listen_address": "127.0.0.1", "grpc_listen_port": 9095,
        })
        self.assertEqual(config["common"]["instance_addr"], "127.0.0.1")
        datasource = yaml.safe_load(self.render("loki-datasource.yml.j2"))["datasources"][0]
        self.assertEqual(datasource["url"], "http://127.0.0.1:3101")

    def test_ingress_exposes_only_the_exact_push_and_readiness_routes(self):
        config = self.render("loki-ingress.conf.j2")
        self.assertEqual(re.findall(r"\blisten\s+([^;]+);", config), ["0.0.0.0:3100"])
        self.assertEqual(set(re.findall(r"\ballow\s+([^;]+);", config)), {
            "127.0.0.1/32", "192.0.2.50/32", "192.0.2.10/32", "192.0.2.11/32",
        })
        self.assertIn("deny all;", config)
        self.assertNotIn("include ", config)
        locations = re.findall(r"location\s+(=\s+)?([^\s{]+)\s*\{", config)
        self.assertEqual(locations, [("= ", "/loki/api/v1/push"), ("= ", "/ready"), ("", "/")])
        self.assertEqual(re.findall(r"proxy_pass\s+([^;]+);", config), [
            "http://127.0.0.1:3101/loki/api/v1/push", "http://127.0.0.1:3101/ready",
        ])
        self.assertIn("if ($request_method != POST) { return 405; }", config)
        self.assertIn("if ($request_method != GET) { return 405; }", config)
        self.assertIn("location / {\n            return 403;", config)
        self.assertIn("client_max_body_size 0;", config)
        self.assertIn("proxy_request_buffering off;", config)
        self.assertIn("proxy_http_version 1.1;", config)

    def test_retention_fixture_replaces_both_ports_without_duplicate_grpc_keys(self):
        source = ast.parse((ROLE / "files/verify_retention.py").read_text())
        transforms = []
        started = False
        for statement in source.body:
            if isinstance(statement, ast.Assert):
                started = True
            if not started:
                continue
            if isinstance(statement, ast.Assert) or (
                isinstance(statement, ast.Assign) and
                isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == "config"
            ):
                transforms.append(statement)
            else:
                break
        namespace = {"config": self.render("loki.yml.j2"), "root": Path("/isolated-fixture")}
        exec(compile(ast.Module(body=transforms, type_ignores=[]), "retention-transforms", "exec"), namespace)
        config = namespace["config"]
        server = yaml.safe_load(config)["server"]
        self.assertEqual(server["http_listen_port"], 13100)
        self.assertEqual(server["grpc_listen_port"], 19095)
        self.assertEqual(config.count("grpc_listen_address:"), 1)
        self.assertEqual(config.count("grpc_listen_port:"), 1)

    def test_startup_blocks_vendor_configuration_and_validates_before_replacement(self):
        top = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        core = next(task["block"] for task in top if task["name"] == "Install centralized logging core")
        names = [task["name"] for task in core]
        expected = [
            "Block a new Nginx service until its restricted configuration is installed",
            "Install pinned centralized logging packages",
            "Validate Loki and ingress configurations before installation",
            "Install centralized logging configuration",
            "Check whether Loki has applied its private listener configuration",
            "Restart changed or outdated centralized logging services",
            "Wait for Loki readiness",
            "Start the restricted Loki ingress",
        ]
        positions = [names.index(name) for name in expected]
        self.assertEqual(positions, sorted(positions))
        package = core[names.index("Install pinned centralized logging packages")]
        self.assertIn("exit 101", package["ansible.builtin.command"]["argv"][-1])
        validation = core[names.index("Validate Loki and ingress configurations before installation")]
        self.assertEqual({item["name"] for item in validation["loop"]}, {"loki", "nginx"})

    def test_interrupted_runs_apply_pending_listener_and_ingress_changes(self):
        top = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        core = next(task["block"] for task in top if task["name"] == "Install centralized logging core")
        by_name = {task["name"]: task for task in core}
        probe = by_name["Check whether Loki has applied its private listener configuration"]
        self.assertFalse(probe["failed_when"])
        self.assertIn("http://127.0.0.1:3101/ready", probe["ansible.builtin.command"]["argv"])
        restart = by_name["Restart changed or outdated centralized logging services"]
        pending = self.environment.compile_expression(restart["when"])
        for changed, returncode, expected in ((False, 0, False), (False, 7, True), (False, 22, True), (True, 0, True)):
            self.assertEqual(pending(
                _centralized_logging_core_config={"changed": changed},
                _centralized_logging_loki_before_restart={"rc": returncode},
            ), expected)
        reload_task = by_name["Reload the validated Loki ingress policy"]
        self.assertNotIn("when", reload_task)
        self.assertFalse(reload_task["changed_when"])
        reload_command = reload_task["ansible.builtin.command"]["argv"][-1]
        self.assertLess(reload_command.index("nginx -t"), reload_command.index("systemctl reload nginx"))


if __name__ == "__main__":
    unittest.main()
