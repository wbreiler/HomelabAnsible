"""Keep Deluge's advertised listening port aligned with Proton's NAT-PMP lease."""

from pathlib import Path

from deluge.ui.client import client
from twisted.internet import defer, reactor, task


def read_port(value):
    port = int(value.strip())
    if not 1 <= port <= 65535:
        raise ValueError("Invalid forwarded port")
    return port


@defer.inlineCallbacks
def synchronize():
    try:
        port = read_port(Path("/tmp/gluetun/forwarded_port").read_text())
        if not client.connected():
            auth = next(
                line.split(":")
                for line in Path("/config/auth").read_text().splitlines()
                if line.startswith("localclient:")
            )
            yield client.connect("127.0.0.1", 58846, auth[0], auth[1])
        current = yield client.core.get_config_values(["listen_ports", "random_port"])
        if list(current["listen_ports"]) != [port, port] or current["random_port"]:
            yield client.core.set_config({"listen_ports": [port, port], "random_port": False})
            print(f"Deluge listening port synchronized: {port}", flush=True)
    except Exception as error:
        # Retry after VPN reconnects or Deluge restarts. Do not print credentials.
        print(f"Port synchronization deferred: {type(error).__name__}", flush=True)


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        assert read_port(" 49152\n") == 49152
        for invalid in ("0", "65536", "not-a-port"):
            try:
                read_port(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(invalid)
    else:
        task.LoopingCall(synchronize).start(30)
        reactor.run()
