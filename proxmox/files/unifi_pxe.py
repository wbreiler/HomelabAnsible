#!/usr/bin/env python3
"""Preview or apply narrowly scoped UniFi DHCP network-boot settings over SSH."""
import argparse
import copy
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import ssl
import subprocess
import sys
import urllib.request


def plan(config, networks):
    server = str(ipaddress.IPv4Address(config["server"]))
    filename = config["filename"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", filename):
        raise ValueError("Boot filename must be a plain filename without whitespace")
    result = []
    seen = set()
    for target in config["networks"]:
        vlan = target["vlan"]
        if type(vlan) is not int or not 1 <= vlan <= 4094 or vlan in seen:
            raise ValueError("Invalid or duplicate VLAN")
        seen.add(vlan)
        matches = [n for n in networks if
                   (n.get("vlan") if n.get("vlan_enabled") else 1) == vlan
                   and n.get("purpose") == "corporate"]
        if len(matches) != 1 or not matches[0].get("enabled", True):
            raise ValueError(f"VLAN {vlan} must be an enabled UniFi-routed network")
        network = matches[0]
        if network.get("dhcp_relay_enabled"):
            raise ValueError(f"VLAN {vlan} uses a DHCP relay")
        changes = {"dhcpd_boot_enabled": True, "dhcpd_boot_server": server,
                   "dhcpd_boot_filename": filename}
        if "dhcp_range" in target:
            interface = ipaddress.IPv4Interface(network["ip_subnet"])
            start, stop = map(ipaddress.IPv4Address, target["dhcp_range"])
            if not (interface.network.network_address < start <= stop
                    < interface.network.broadcast_address
                    and start in interface.network and stop in interface.network
                    and not start <= interface.ip <= stop):
                raise ValueError(f"Invalid DHCP range for VLAN {vlan}")
            changes.update(dhcpd_enabled=True, dhcpd_start=str(start), dhcpd_stop=str(stop))
        elif not network.get("dhcpd_enabled"):
            raise ValueError(f"VLAN {vlan} needs an explicitly reviewed DHCP range")
        changes = {k: v for k, v in changes.items() if network.get(k) != v}
        if changes:
            result.append((network, changes))
    return result


def remote_main(payload):
    # SSH authenticates the transport; the self-signed HTTPS endpoint is loopback only.
    context = ssl._create_unverified_context()
    base = "https://127.0.0.1/proxy/network/api/s/default/rest/networkconf"

    def request(suffix="", body=None):
        req = urllib.request.Request(
            base + suffix, method="GET" if body is None else "PUT",
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-API-Key": payload["key"], "Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            result = json.load(response)
        if result.get("meta", {}).get("rc") != "ok":
            raise RuntimeError("UniFi rejected the network request")
        return result["data"]

    networks = request()
    changes = plan(payload["config"], networks)
    print(json.dumps({"changes": [{"name": n["name"], "set": c} for n, c in changes]}), flush=True)
    if not payload["apply"] or not changes:
        return
    os.umask(0o077)
    backup = Path("/data/homelab-backups") / datetime.datetime.now(
        datetime.timezone.utc).strftime("pxe-%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, mode=0o700)
    (backup / "networks.json").write_text(json.dumps(networks, indent=2) + "\n")
    (backup / "changes.json").write_text(json.dumps(
        [{"id": n["_id"], "set": c} for n, c in changes], indent=2) + "\n")
    print(f"Backup: {backup}", flush=True)
    for original, patch in changes:
        # Re-read before each write so a concurrent UI edit cannot be overwritten.
        current = next(n for n in request() if n["_id"] == original["_id"])
        if current != original:
            raise RuntimeError("Network changed since preview; rerun after review")
        request("/" + original["_id"], patch)
        saved = next(n for n in request() if n["_id"] == original["_id"])
        expected = copy.deepcopy(original)
        expected.update(patch)
        if saved != expected:
            raise RuntimeError(f"Unexpected network readback; inspect {backup} before continuing")
        print(f"Verified {original['name']}", flush=True)
    if plan(payload["config"], request()):
        raise RuntimeError("Network boot settings did not converge")


def main():
    if sys.argv[1:] == ["--remote"]:
        remote_main(json.load(sys.stdin))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.key_file.stat().st_mode & 0o077:
        parser.error("API key file must have mode 0600")
    key = args.key_file.read_text().strip()
    if not key:
        parser.error("API key file is empty")
    payload = {"key": key, "config": json.loads(args.config.read_text()), "apply": args.apply}
    subprocess.run([
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes", "-i", args.identity_file, args.ssh_target,
        "python3 -c " + shlex.quote(Path(__file__).read_text()) + " --remote",
    ], input=json.dumps(payload), text=True, check=True)


if __name__ == "__main__":
    main()
