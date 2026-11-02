#!/usr/bin/env python3
"""Add UniFi A records through its supported API, carried over verified SSH."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shlex
import ssl
import subprocess
import sys
import urllib.request


def missing_records(desired, existing):
    """Reject all conflicts before writing any records. Never delete records."""
    names = set()
    missing = []
    for record in desired:
        name = record["domain"]
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name) or len(name) > 127:
            raise ValueError(f"Invalid DNS name: {name!r}")
        ipaddress.IPv4Address(record["ipv4Address"])
        if name in names:
            raise ValueError(f"Duplicate desired name: {name}")
        names.add(name)
        matches = [r for r in existing if r.get("domain", "").rstrip(".").lower() == name]
        if matches:
            if len(matches) != 1 or any(matches[0].get(k) != record[k] for k in ("type", "enabled", "ipv4Address")):
                raise ValueError(f"Existing DNS policy conflicts with {name}; review it manually")
        else:
            missing.append(record)
    return missing


def remote_main(payload):
    # TLS stays on gateway loopback; SSH verifies and encrypts the network transport.
    context = ssl._create_unverified_context()
    base = "https://127.0.0.1/proxy/network/integration/v1"

    def request(path, body=None):
        req = urllib.request.Request(
            base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-API-Key": payload["key"], "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            return json.load(response)

    def pages(path):
        records = []
        while True:
            page = request(f"{path}?limit=200&offset={len(records)}")
            records.extend(page["data"])
            if len(records) >= page["totalCount"]:
                return records
            if not page["data"]:
                raise RuntimeError("API pagination stopped before totalCount")

    sites = [s for s in pages("/sites") if s["internalReference"] == payload["site"]]
    if len(sites) != 1:
        raise ValueError("Expected exactly one matching UniFi site")
    path = f"/sites/{sites[0]['id']}/dns/policies"
    desired = [dict(r, type="A_RECORD", enabled=True, ttlSeconds=300) for r in payload["records"]]
    missing = missing_records(desired, pages(path))
    print(json.dumps({"create": [r["domain"] for r in missing], "unchanged": len(desired) - len(missing)}), flush=True)
    if payload["apply"]:
        for record in missing:
            result = request(path, record)
            print(json.dumps({"created": record["domain"], "id": result["id"]}), flush=True)
        if missing_records(desired, pages(path)):
            raise RuntimeError("DNS policy readback did not match desired records")
        print(f"Verified {len(desired)} DNS policies", flush=True)


def main():
    if sys.argv[1:] == ["--remote"]:
        remote_main(json.load(sys.stdin))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--site", default="default")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.key_file.stat().st_mode & 0o077:
        parser.error("API key file must have mode 0600")
    payload = {"key": args.key_file.read_text().strip(), "records": json.loads(args.records.read_text()),
               "site": args.site, "apply": args.apply}
    if not payload["key"]:
        parser.error("API key file is empty")
    command = "python3 -c " + shlex.quote(Path(__file__).read_text()) + " --remote"
    subprocess.run([
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes", "-i", args.identity_file, args.ssh_target, command,
    ], input=json.dumps(payload), text=True, check=True)


if __name__ == "__main__":
    main()
