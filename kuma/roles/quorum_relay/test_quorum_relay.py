#!/usr/bin/env python3
"""Self-check for files/quorum_relay.py. Run directly: python3 test_quorum_relay.py
Only exercises the pure vote-tallying logic -- no HTTP server, no network.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "files"))
import quorum_relay as qr  # noqa: E402


class TallyTests(unittest.TestCase):
    def test_majority_down_wins(self):
        votes = {"ms": ("down", 100), "tx": ("down", 100), "co": ("up", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx", "co"], 600, 100), "down")

    def test_minority_down_loses(self):
        votes = {"ms": ("down", 100), "tx": ("up", 100), "co": ("up", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx", "co"], 600, 100), "up")

    def test_stale_vote_ignored(self):
        votes = {"ms": ("down", 0), "tx": ("down", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx"], 600, 1000), "up")

    def test_missing_vote_treated_as_abstain(self):
        votes = {"ms": ("down", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx", "co"], 600, 100), "up")

    def test_two_of_two_ties_broken_by_agreement(self):
        # With only 2 known sites, majority is 2 -- unanimous agreement
        # required, same weak guarantee as the pre-quorum design. This is
        # exactly why a 3rd site matters: majority of 3 is 2, not 3.
        votes = {"ms": ("down", 100), "tx": ("down", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx"], 600, 100), "down")
        votes = {"ms": ("down", 100), "tx": ("up", 100)}
        self.assertEqual(qr.tally(votes, ["ms", "tx"], 600, 100), "up")


class QuorumStateTests(unittest.TestCase):
    def test_pages_once_on_down_transition(self):
        state = qr.QuorumState(["ms", "tx", "co"], 600)
        result = state.record("svc", "ms", "down", 100)
        self.assertFalse(state.transitioned("svc", result))  # 1/3, no majority yet
        result = state.record("svc", "tx", "down", 100)
        self.assertTrue(state.transitioned("svc", result))  # 2/3 now -- pages
        result = state.record("svc", "co", "down", 100)
        self.assertFalse(state.transitioned("svc", result))  # already alerting, no repage

    def test_recovery_fires_as_soon_as_majority_clears(self):
        # 3 known sites, majority 2. Escalation needs 2 down; de-escalation
        # only needs down-votes to drop back below 2 -- it doesn't need
        # every site to individually report up.
        state = qr.QuorumState(["ms", "tx", "co"], 600)
        state.record("svc", "ms", "down", 100)
        result = state.record("svc", "tx", "down", 100)
        self.assertTrue(state.transitioned("svc", result))  # 2/3 down -- pages
        state.record("svc", "co", "down", 100)

        result = state.record("svc", "ms", "up", 200)
        self.assertFalse(state.transitioned("svc", result))  # still 2/3 down -- stays alerting

        result = state.record("svc", "tx", "up", 200)
        self.assertTrue(state.transitioned("svc", result))  # only 1/3 down now -- recovers


class ParseKumaStatusTests(unittest.TestCase):
    def test_status_one_is_up(self):
        self.assertEqual(qr.parse_kuma_status({"heartbeat": {"status": 1}}), "up")

    def test_other_status_is_down(self):
        self.assertEqual(qr.parse_kuma_status({"heartbeat": {"status": 0}}), "down")

    def test_missing_status_fails_toward_down(self):
        self.assertEqual(qr.parse_kuma_status({}), "down")


if __name__ == "__main__":
    unittest.main()
