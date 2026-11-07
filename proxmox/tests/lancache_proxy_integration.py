"""Run with both rendered nginx configs, startup hook, and locally pinned image."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


def run(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        print(error.output, file=sys.stderr)
        raise


def main(config, cache_config, hook, image):
    assert "@sha256:" in image, "Use the pinned LANCache image"
    name = "lancache-range-test-" + uuid.uuid4().hex[:12]
    payload = b"range-test-" * 200000
    with tempfile.TemporaryDirectory(prefix="lancache-range-test-") as directory:
        root = Path(directory)
        (root / "range-body").write_bytes(payload)
        (root / "upstream.conf").write_text(Path(config).read_text())
        (root / "cache-upstream.conf").write_text(Path(cache_config).read_text())
        (root / "upstream-hook.sh").write_text(Path(hook).read_text())
        (root / "upstream-hook.sh").chmod(0o755)
        (root / "nginx.conf").write_text("""user root;
pid /tmp/nginx.pid;
error_log stderr;
events {}
http {
    log_format connections '$server_port $connection';
    access_log /tmp/connections.log connections;
    include /fixture/upstream.conf;
    server {
        listen 127.0.0.1:3129;
        location / { root /fixture; max_ranges 0; }
        location = /redirect { return 302 http://127.0.0.1:3129/range-body; }
    }
    server {
        listen 8080;
        location / {
            slice 1m;
            proxy_set_header Range $slice_range;
            include /fixture/cache-upstream.conf;
        }
    }
}
""")
        try:
            run("docker", "run", "-d", "--name", name, "--pull", "never",
                "--network", "none", "--tmpfs", "/tmp",
                "--tmpfs", "/data/logs", "-v", directory + ":/fixture:ro",
                "--entrypoint", "nginx", image, "-c", "/fixture/nginx.conf",
                "-g", "daemon off;")
            for path, byte_range, status, expected in [
                ("/range-body", None, "200", payload),
                ("/range-body", "bytes=1048576-2097151", "206", payload[1048576:2097152]),
                ("/redirect", None, "200", payload),
            ]:
                args = ["docker", "exec", name, "curl", "-fsS", "--max-time", "10",
                        "--retry", "5", "--retry-connrefused", "--retry-delay", "1",
                        "-o", "/tmp/received", "-w", "%{http_code} %{size_download}"]
                if byte_range:
                    args += ["-H", "Range: " + byte_range]
                result = run(*args, "http://127.0.0.1:8080" + path)
                assert result == f"{status} {len(expected)}", result
                digest = run("docker", "exec", name, "sha256sum", "/tmp/received").split()[0]
                assert digest == hashlib.sha256(expected).hexdigest()
                print(f"PASS {path} {byte_range or 'complete response'}")
            lines = run("docker", "exec", name, "cat", "/tmp/connections.log").splitlines()
            connections = [line.split()[1] for line in lines if line.startswith("3128 ")]
            assert len(connections) >= 6 and len(set(connections)) == 1, connections
            print("PASS adjacent slices reuse one local proxy connection")
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL)

        # Give the isolated image a worker subnet that curl can bind on loopback.
        fixture, count = re.subn(r"(?m)^(    )[0-9./]+ 0;$", r"\g<1>127.42.0.0/24 0;",
                                 Path(config).read_text())
        assert count == 1, "Expected one worker subnet in the rendered geo block"
        (root / "upstream.conf").write_text(fixture)
        try:
            run("docker", "run", "-d", "--name", name, "--pull", "never",
                "--network", "none", "--tmpfs", "/data/cache:size=64m", "--tmpfs", "/data/logs",
                "-e", "CACHE_INDEX_SIZE=1m", "-e", "CACHE_DISK_SIZE=32m", "-e", "MIN_FREE_DISK=0",
                "-v", str(root / "upstream.conf") + ":/etc/lancache-upstream.conf:ro",
                "-v", str(root / "cache-upstream.conf") + ":/etc/lancache-cache-upstream.conf:ro",
                "-v", str(root / "upstream-hook.sh") + ":/hooks/entrypoint-pre.d/99_upstream.sh:ro", image)
            run("docker", "exec", name, "curl", "-fsS", "--max-time", "10", "--retry", "20",
                "--retry-connrefused", "--retry-delay", "1", "http://127.0.0.1/lancache-heartbeat")
            active = run("docker", "exec", name, "nginx", "-T")
            assert "proxy_force_ranges on;" in active and "server 127.0.0.1:3129;" in active
            print("PASS image startup hooks and HTTP readiness")
            for source in ("127.42.0.4", "127.42.0.99", "127.0.0.1"):
                status = run("docker", "exec", name, "curl", "-fsS", "--max-time", "5",
                             "--interface", source, "-H", "X-Forwarded-For: 127.42.0.4",
                             "-o", "/dev/null", "-w", "%{http_code}",
                             "http://127.0.0.1/lancache-heartbeat?analytics-test=" + source)
                assert status == "204", status
            access = run("docker", "exec", name, "cat", "/data/logs/access.log")
            assert access.count("analytics-test=") == 1 and "analytics-test=127.0.0.1 " in access
            print("PASS only real client requests enter the dashboard log")
        except BaseException:
            print(run("docker", "logs", name), file=sys.stderr)
            raise
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main(*sys.argv[1:])
