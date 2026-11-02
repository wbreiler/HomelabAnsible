#!/usr/bin/env python3
"""Exercise installed routes in a private network namespace; production stays running.

Run as root inside the proxy guest: python3 verify_local_services_ingress.py
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def main():
    if sys.argv[1:] != ["--isolated"]:
        subprocess.run(["unshare", "--net", sys.executable, __file__, "--isolated"], check=True)
        return
    run("ip", "link", "set", "lo", "up")
    for address in ("10.10.99.2/32", "203.0.113.2/32"):
        run("ip", "addr", "add", address, "dev", "lo")
    config = Path("/etc/nginx/conf.d/homelab-local-services.conf").read_text()
    names = re.findall(r"server_name ([^;]+);", config)
    if not names:
        raise RuntimeError("No installed local service routes")
    # Replace only the upstream with a response; exercise the actual admission rules.
    config = re.sub(r"proxy_pass [^;]+;", "return 204;", config)
    config = re.sub(r"proxy_redirect [^;]+;", "", config)
    config = re.sub(r"(?:access_log|error_log) [^;]+;", "", config)
    with tempfile.TemporaryDirectory(prefix="local-services-ingress-") as directory:
        root = Path(directory)
        fixture = root / "nginx.conf"
        fixture.write_text(
            f"pid {root / 'nginx.pid'}; error_log {root / 'error.log'};\n"
            "events {}\nhttp { access_log off;\n"
            "set_real_ip_from 203.0.113.0/24; real_ip_header X-Forwarded-For;\n"
            + config + "\n}\n"
        )
        run("nginx", "-p", directory, "-c", str(fixture), "-t")
        run("nginx", "-p", directory, "-c", str(fixture))
        try:
            for name in names:
                for source, scheme, forwarded, expected in (
                    ("10.10.99.2", "https", "", "204"),
                    ("10.10.99.2", "http", "", "301"),
                    ("203.0.113.2", "https", "", "403"),
                    ("203.0.113.2", "http", "", "403"),
                    ("203.0.113.2", "https", "10.10.99.2", "403"),
                ):
                    port = "443" if scheme == "https" else "80"
                    status = run("curl", "--noproxy", "*", "-ksS", "--max-time", "5", "--interface", source,
                                 "--resolve", f"{name}:{port}:127.0.0.1", "-H", f"X-Forwarded-For: {forwarded}",
                                 "-o", "/dev/null", "-w", "%{http_code}", f"{scheme}://{name}/")
                    assert status == expected, (name, source, scheme, forwarded, status, expected)
        finally:
            run("nginx", "-p", directory, "-c", str(fixture), "-s", "quit")
    print(f"PASS: {len(names)} routes allow LAN HTTPS, redirect LAN HTTP, and deny public peers including forged forwarding headers")


if __name__ == "__main__":
    main()
