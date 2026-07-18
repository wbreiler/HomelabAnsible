#!/usr/bin/env python3
"""Keep Proxmox guest IP tags synchronized with detected IPv4 addresses."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_CONFIG_PATH = Path("/opt/iptag/iptag.conf")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
MANAGED_TAG_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
NETWORK_LINE_PATTERN = re.compile(r"^net\d+:\s*(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Settings:
    networks: tuple[ipaddress.IPv4Network, ...]
    tag_format: str
    loop_interval: int
    debug: bool
    command_timeout: int


def log(level: str, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}", flush=True)


def debug(settings: Settings, message: str) -> None:
    if settings.debug:
        log("DEBUG", message)


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_config(path: Path) -> Settings:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read configuration {path}: {error}") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    raw_cidrs = values.get("CIDR_LIST", "")
    cidr_values = [item for item in re.split(r"[\s,]+", raw_cidrs) if item]
    if not cidr_values:
        raise ValueError("CIDR_LIST must contain at least one IPv4 network")

    networks: list[ipaddress.IPv4Network] = []
    for cidr in cidr_values:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as error:
            raise ValueError(f"invalid CIDR {cidr!r}: {error}") from error
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError(f"CIDR {cidr!r} is not an IPv4 network")
        networks.append(network)

    tag_format = values.get("TAG_FORMAT", "last_octet")
    if tag_format not in {"last_two_octets", "last_octet", "full"}:
        raise ValueError(f"unsupported TAG_FORMAT {tag_format!r}")

    try:
        loop_interval = int(values.get("LOOP_INTERVAL", "300"))
        command_timeout = int(values.get("COMMAND_TIMEOUT", "8"))
    except ValueError as error:
        raise ValueError("LOOP_INTERVAL and COMMAND_TIMEOUT must be integers") from error

    if not 300 <= loop_interval <= 7200:
        raise ValueError("LOOP_INTERVAL must be between 300 and 7200 seconds")
    if command_timeout <= 0:
        raise ValueError("COMMAND_TIMEOUT must be positive")

    return Settings(
        networks=tuple(networks),
        tag_format=tag_format,
        loop_interval=loop_interval,
        debug=parse_bool(values.get("DEBUG", "false")),
        command_timeout=command_timeout,
    )


def run_command(
    arguments: Sequence[str],
    settings: Settings,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    debug(settings, f"running: {' '.join(arguments)}")
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.command_timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if check:
            raise RuntimeError(f"command failed: {' '.join(arguments)}: {error}") from error
        debug(settings, f"command unavailable: {' '.join(arguments)}: {error}")
        return subprocess.CompletedProcess(arguments, 1, "", str(error))

    if check and result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(arguments)}: {error_text}"
        )
    return result


def parse_guest_list(output: str) -> dict[str, str]:
    guests: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].isdigit():
            if fields[1].lower() in {"running", "stopped"}:
                status = fields[1].lower()
            elif len(fields) >= 3:
                status = fields[2].lower()
            else:
                continue
            guests[fields[0]] = status
    return guests


def get_guest_lists(settings: Settings) -> dict[str, dict[str, str]]:
    return {
        "lxc": parse_guest_list(run_command(["pct", "list"], settings, check=True).stdout),
        "vm": parse_guest_list(run_command(["qm", "list"], settings, check=True).stdout),
    }


def get_guest_config(guest_type: str, vmid: str, settings: Settings) -> str:
    command = "pct" if guest_type == "lxc" else "qm"
    return run_command([command, "config", vmid], settings, check=True).stdout


def parse_current_tags(config: str) -> list[str]:
    for line in config.splitlines():
        if line.startswith("tags:"):
            return [tag for tag in line.split(":", 1)[1].strip().split(";") if tag]
    return []


def valid_ipv4_values(values: Iterable[str]) -> list[ipaddress.IPv4Address]:
    addresses: set[ipaddress.IPv4Address] = set()
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address) and not address.is_loopback:
            addresses.add(address)
    return sorted(addresses)


def parse_static_lxc_addresses(config: str) -> list[ipaddress.IPv4Address]:
    values: list[str] = []
    for network_config in NETWORK_LINE_PATTERN.findall(config):
        for option in network_config.split(","):
            key, separator, value = option.partition("=")
            if separator and key.strip() == "ip":
                values.append(value.split("/", 1)[0].strip())
    return valid_ipv4_values(values)


def parse_mac_addresses(config: str) -> list[str]:
    return sorted({match.lower() for match in MAC_PATTERN.findall(config)})


def get_neighbor_map(settings: Settings) -> dict[str, ipaddress.IPv4Address]:
    result = run_command(["ip", "-4", "neighbor", "show"], settings)
    neighbors: dict[str, ipaddress.IPv4Address] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if "lladdr" not in fields or not fields:
            continue
        try:
            address = ipaddress.ip_address(fields[0])
            mac = fields[fields.index("lladdr") + 1].lower()
        except (ValueError, IndexError):
            continue
        if isinstance(address, ipaddress.IPv4Address):
            neighbors[mac] = address
    return neighbors


def addresses_for_macs(
    mac_addresses: Iterable[str],
    neighbors: dict[str, ipaddress.IPv4Address],
) -> list[ipaddress.IPv4Address]:
    return sorted({neighbors[mac] for mac in mac_addresses if mac in neighbors})


def get_lxc_addresses(
    vmid: str,
    status: str,
    config: str,
    neighbors: dict[str, ipaddress.IPv4Address],
    settings: Settings,
) -> list[ipaddress.IPv4Address]:
    if status != "running":
        return []

    static_addresses = parse_static_lxc_addresses(config)
    if static_addresses:
        return static_addresses

    result = run_command(
        ["pct", "exec", vmid, "--", "ip", "-4", "-o", "addr", "show", "scope", "global"],
        settings,
    )
    direct_addresses = valid_ipv4_values(IPV4_PATTERN.findall(result.stdout))
    if direct_addresses:
        return direct_addresses

    return addresses_for_macs(parse_mac_addresses(config), neighbors)


def guest_agent_enabled(config: str) -> bool:
    for line in config.splitlines():
        if not line.startswith("agent:"):
            continue
        value = line.split(":", 1)[1].strip()
        return value == "1" or "enabled=1" in value
    return False


def get_vm_addresses(
    vmid: str,
    status: str,
    config: str,
    neighbors: dict[str, ipaddress.IPv4Address],
    settings: Settings,
) -> list[ipaddress.IPv4Address]:
    if status != "running":
        return []

    if guest_agent_enabled(config):
        result = run_command(
            ["qm", "guest", "cmd", vmid, "network-get-interfaces"],
            settings,
        )
        agent_addresses = valid_ipv4_values(IPV4_PATTERN.findall(result.stdout))
        if agent_addresses:
            return agent_addresses

    return addresses_for_macs(parse_mac_addresses(config), neighbors)


def address_is_allowed(address: ipaddress.IPv4Address, settings: Settings) -> bool:
    return any(address in network for network in settings.networks)


def format_address(address: ipaddress.IPv4Address, settings: Settings) -> str:
    octets = str(address).split(".")
    if settings.tag_format == "last_octet":
        return octets[-1]
    if settings.tag_format == "last_two_octets":
        return ".".join(octets[-2:])
    return str(address)


def desired_tags(
    current_tags: Sequence[str],
    addresses: Iterable[ipaddress.IPv4Address],
    settings: Settings,
) -> list[str]:
    address_tags = [
        format_address(address, settings)
        for address in addresses
        if address_is_allowed(address, settings)
    ]
    user_tags = [tag for tag in current_tags if not MANAGED_TAG_PATTERN.fullmatch(tag)]
    return list(dict.fromkeys([*address_tags, *user_tags]))


def set_guest_tags(
    guest_type: str,
    vmid: str,
    tags: Sequence[str],
    settings: Settings,
) -> None:
    command = "pct" if guest_type == "lxc" else "qm"
    run_command(
        [command, "set", vmid, "--tags", ";".join(tags)],
        settings,
        check=True,
    )


def reconcile_guest(
    guest_type: str,
    vmid: str,
    status: str,
    neighbors: dict[str, ipaddress.IPv4Address],
    settings: Settings,
) -> bool:
    config = get_guest_config(guest_type, vmid, settings)
    current_tags = parse_current_tags(config)

    if guest_type == "lxc":
        addresses = get_lxc_addresses(vmid, status, config, neighbors, settings)
        if not addresses:
            debug(settings, f"LXC {vmid}: no IP detected; leaving tags unchanged")
            return False
    else:
        addresses = get_vm_addresses(vmid, status, config, neighbors, settings)

    next_tags = desired_tags(current_tags, addresses, settings)
    if next_tags == current_tags:
        debug(settings, f"{guest_type.upper()} {vmid}: tags already current")
        return False

    set_guest_tags(guest_type, vmid, next_tags, settings)
    log(
        "CHANGED",
        f"{guest_type.upper()} {vmid}: {';'.join(current_tags)} -> {';'.join(next_tags)}",
    )
    return True


def reconcile_all(settings: Settings) -> int:
    guest_lists = get_guest_lists(settings)
    neighbors = get_neighbor_map(settings)
    failures: list[str] = []
    changes = 0

    for guest_type in ("lxc", "vm"):
        for vmid, status in guest_lists[guest_type].items():
            try:
                changes += int(
                    reconcile_guest(guest_type, vmid, status, neighbors, settings)
                )
            except RuntimeError as error:
                failures.append(f"{guest_type.upper()} {vmid}: {error}")
                log("ERROR", failures[-1])

    if failures:
        raise RuntimeError(f"{len(failures)} guest reconciliation(s) failed")
    return changes


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--once", action="store_true", help="run one reconciliation")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate the configuration and exit",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        settings = read_config(arguments.config)
    except ValueError as error:
        log("ERROR", str(error))
        return 2

    if arguments.check_config:
        log("OK", f"configuration is valid: {arguments.config}")
        return 0

    if arguments.once:
        try:
            changes = reconcile_all(settings)
        except RuntimeError as error:
            log("ERROR", str(error))
            return 1
        log("OK", f"reconciliation complete; {changes} guest(s) changed")
        return 0

    log(
        "OK",
        f"service started; interval={settings.loop_interval}s format={settings.tag_format}",
    )
    while True:
        try:
            changes = reconcile_all(settings)
            log("OK", f"reconciliation complete; {changes} guest(s) changed")
        except RuntimeError as error:
            log("ERROR", str(error))
        time.sleep(settings.loop_interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
