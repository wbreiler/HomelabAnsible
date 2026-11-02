"""Ensure DNS additions never replace unrelated or conflicting policies."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("local_dns", Path(__file__).resolve().parents[1] / "files/local_dns.py")
DNS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DNS)


class LocalDNS(unittest.TestCase):
    def setUp(self):
        self.record = {"domain": "spoolman.example.com", "ipv4Address": "192.0.2.10", "type": "A_RECORD", "enabled": True}

    def test_create_and_repeat(self):
        self.assertEqual(DNS.missing_records([self.record], []), [self.record])
        self.assertEqual(DNS.missing_records([self.record], [dict(self.record, id="existing")]), [])

    def test_conflicts_fail_before_writes(self):
        for change in ({"ipv4Address": "192.0.2.11"}, {"enabled": False}, {"type": "CNAME_RECORD"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                DNS.missing_records([self.record], [dict(self.record, **change)])

    def test_unrelated_policies_are_preserved(self):
        unrelated = dict(self.record, domain="other.example.com")
        self.assertEqual(DNS.missing_records([self.record], [unrelated]), [self.record])

    def test_invalid_and_duplicate_input(self):
        for change in ({"domain": "name; include"}, {"ipv4Address": "999.1.2.3"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                DNS.missing_records([dict(self.record, **change)], [])
        with self.assertRaises(ValueError):
            DNS.missing_records([self.record, self.record], [])
        with self.assertRaises(ValueError):
            DNS.missing_records([self.record], [self.record, self.record])


if __name__ == "__main__":
    unittest.main()
