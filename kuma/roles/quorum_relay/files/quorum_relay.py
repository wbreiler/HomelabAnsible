#!/usr/bin/env python3
"""Local relay between Kuma's webhook notification and Discord for shared
monitors checked redundantly by every quorum site (3+ sites).

Every quorum site runs this. Kuma's webhook notification (local-only) hits
POST /notify here; this tags the event with the site's own name and either
tallies it directly (if this host is the quorum primary) or forwards it to
the primary's POST /report. The primary pages Discord only once a majority
of known sites currently agree a monitor is down -- one flaky path on one
site can't page alone, and a real outage still pages once enough sites
agree.

Best-effort against Kuma's generic webhook notification payload shape,
which is not a stable/versioned contract -- check parse_kuma_status()
first if alerts stop firing after a Kuma upgrade.
"""
import json
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def parse_kuma_status(payload):
    """Kuma's generic webhook sends {"heartbeat": {"status": N}, ...} where
    1 means up. Treat anything else (0=down, 2=pending, 3=maintenance, or a
    missing/unrecognized field) as down -- fail toward alerting, not away
    from it."""
    return "up" if payload.get("heartbeat", {}).get("status") == 1 else "down"


def tally(votes_for_monitor, known_sites, staleness_seconds, now):
    """votes_for_monitor: {site: (status, timestamp)}. A site with no vote,
    or a vote older than staleness_seconds, abstains rather than counting
    either way."""
    down = 0
    for site in known_sites:
        entry = votes_for_monitor.get(site)
        if entry is None:
            continue
        status, ts = entry
        if now - ts > staleness_seconds:
            continue
        if status == "down":
            down += 1
    majority = len(known_sites) // 2 + 1
    return "down" if down >= majority else "up"


class QuorumState:
    def __init__(self, known_sites, staleness_seconds):
        self.known_sites = known_sites
        self.staleness_seconds = staleness_seconds
        self.votes = {}  # monitor_name -> {site: (status, ts)}
        self.alerting = set()  # monitor_names currently paged as down

    def record(self, monitor_name, site, status, now):
        self.votes.setdefault(monitor_name, {})[site] = (status, now)
        return tally(self.votes[monitor_name], self.known_sites, self.staleness_seconds, now)

    def transitioned(self, monitor_name, result):
        """True only on a down/up state change -- so a monitor that stays
        down doesn't re-page on every follow-up report."""
        was_alerting = monitor_name in self.alerting
        if result == "down" and not was_alerting:
            self.alerting.add(monitor_name)
            return True
        if result == "up" and was_alerting:
            self.alerting.discard(monitor_name)
            return True
        return False


def post_json(url, body, timeout=10):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def post_discord(webhook_url, monitor_name, result, votes_for_monitor, known_sites):
    verb = "DOWN" if result == "down" else "recovered (UP)"
    agree = sum(1 for site in known_sites if votes_for_monitor.get(site, (None,))[0] == result)
    content = "[Quorum] {} is {} -- {}/{} sites agree".format(
        monitor_name, verb, agree, len(known_sites)
    )
    post_json(webhook_url, {"content": content})


def handle_report(config, state, report):
    now = time.time()
    result = state.record(report["monitor"], report["site"], report["status"], now)
    if state.transitioned(report["monitor"], result):
        post_discord(
            config["discord_webhook_url"],
            report["monitor"],
            result,
            state.votes[report["monitor"]],
            config["known_sites"],
        )


def make_handler(config, state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep this out of the systemd journal; only errors matter

        def _read_json(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw or b"{}")

        def _respond(self, code=200):
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if self.path == "/notify":
                payload = self._read_json()
                report = {
                    "site": config["site_name"],
                    "monitor": payload.get("monitor", {}).get("name", "unknown"),
                    "status": parse_kuma_status(payload),
                }
                if config["is_primary"]:
                    handle_report(config, state, report)
                else:
                    try:
                        post_json(config["primary_url"] + "/report", report)
                    except Exception:
                        pass  # primary unreachable this round -- vote is simply missing
                self._respond()
            elif self.path == "/report" and config["is_primary"]:
                handle_report(config, state, self._read_json())
                self._respond()
            else:
                self._respond(404)

    return Handler


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        config = json.load(f)
    state = QuorumState(config["known_sites"], config["staleness_seconds"])
    server = ThreadingHTTPServer(("0.0.0.0", config["port"]), make_handler(config, state))
    server.serve_forever()


if __name__ == "__main__":
    main()
