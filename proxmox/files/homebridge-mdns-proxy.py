#!/usr/bin/env python3
"""Publish existing, paired HomeKit bridges on one gateway interface."""

import ipaddress
import json
import re
import socket
import sys
import time


def validate(config):
    ipaddress.IPv4Address(config["address"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", config["interface"]):
        raise ValueError("Invalid interface")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,63}\.local", config["hostname"]):
        raise ValueError("Use a .local hostname")
    services = config["services"]
    if not 1 <= len(services) <= 16:
        raise ValueError("Supply 1–16 existing bridges")
    identities = set()
    names = set()
    for service in services:
        txt = service["txt"]
        if not 1 <= len(service["name"].encode()) <= 63 or service["name"] in names:
            raise ValueError("Bridge names must be unique and fit a DNS label")
        if type(service["port"]) is not int or not 1 <= service["port"] <= 65535:
            raise ValueError("Invalid bridge port")
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", txt["id"]):
            raise ValueError("Invalid HomeKit bridge identity")
        if txt["id"] in identities or txt["sf"] != "0":
            raise ValueError("Publish distinct, already-paired bridges only")
        if not 1 <= int(txt["c#"]) <= 65535:
            raise ValueError("Invalid HomeKit configuration version")
        if any(not isinstance(v, str) or len((k + "=" + v).encode()) > 255 for k, v in txt.items()):
            raise ValueError("Invalid DNS TXT record")
        identities.add(txt["id"])
        names.add(service["name"])
    return config


def main():
    with open(sys.argv[1]) as stream:
        config = validate(json.load(stream))
    if sys.argv[2:] == ["--check"]:
        print("Validated HomeKit advertisements")
        return

    import dbus  # Provided by the gateway's existing Avahi installation.

    bus = dbus.SystemBus()
    server = dbus.Interface(bus.get_object("org.freedesktop.Avahi", "/"), "org.freedesktop.Avahi.Server")
    group = dbus.Interface(
        bus.get_object("org.freedesktop.Avahi", server.EntryGroupNew()), "org.freedesktop.Avahi.EntryGroup"
    )
    interface = socket.if_nametoindex(config["interface"])
    group.AddAddress(interface, 0, dbus.UInt32(0), config["hostname"], config["address"])
    # shortcut: refresh the manifest after bridge identity, port, pairing, or accessory-list changes.
    for service in config["services"]:
        txt = [dbus.ByteArray((key + "=" + value).encode()) for key, value in service["txt"].items()]
        group.AddService(
            interface, 0, dbus.UInt32(0), service["name"], "_hap._tcp", "local",
            config["hostname"], dbus.UInt16(service["port"]), txt,
        )
    group.Commit()
    print("Published %d HomeKit bridges on %s" % (len(config["services"]), config["interface"]), flush=True)
    try:
        while True:
            time.sleep(5)
            if group.GetState() != 2:
                raise RuntimeError("HomeKit advertisements are not established")
    finally:
        group.Free()


if __name__ == "__main__":
    main()
