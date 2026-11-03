"""Validate the limited DHCP configuration before rendering EOS commands."""
import ipaddress
import re


def network_boot_config(config):
    server = str(ipaddress.IPv4Address(config["server"]))
    filename = config["filename"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", filename):
        raise ValueError("Invalid boot filename")
    lines = ["dhcp server", f"   tftp server option 66 ipv4 {server}",
             f"   tftp server file ipv4 {filename}"]
    seen = set()
    for scope in config.get("new_scopes", []):
        vlan = scope["vlan"]
        if not isinstance(vlan, int) or isinstance(vlan, bool) or vlan not in (20, 30) or vlan in seen:
            raise ValueError("New DHCP scopes are restricted to VLANs 20 and 30")
        seen.add(vlan)
        subnet = ipaddress.IPv4Network(scope["subnet"])
        gateway = ipaddress.IPv4Address(scope["gateway"])
        dns = ipaddress.IPv4Address(scope["dns"])
        start, stop = map(ipaddress.IPv4Address, scope["range"])
        if not (subnet.network_address < start <= stop < subnet.broadcast_address
                and start in subnet and stop in subnet and gateway in subnet
                and gateway not in (subnet.network_address, subnet.broadcast_address)
                and not start <= gateway <= stop):
            raise ValueError("DHCP range must stay inside its subnet and exclude its gateway")
        lines.extend([f"   subnet {subnet}", f"      range {start} {stop}",
                      f"      dns server {dns}", f"      default-gateway {gateway}"])
    for vlan in sorted(seen):
        lines.extend([f"interface Vlan{vlan}", "   dhcp server ipv4"])
    return "\n".join(lines) + "\n"


class FilterModule:
    def filters(self):
        return {"network_boot_config": network_boot_config}
