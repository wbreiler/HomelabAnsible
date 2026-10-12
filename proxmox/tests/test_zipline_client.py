"""Verify multipart upload construction and returned host validation."""
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "client", Path(__file__).resolve().parents[1] / "files/zipline/screenshot-upload.py"
)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Response:
    url = "https://i.wbreiler.com/example.png"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps({"files": [{"url": self.url}]}).encode()


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "shot.png"
    path.write_bytes(b"png-content")

    def send(request, timeout):
        assert request.get_header("Authorization") == "private-token"
        assert request.get_header("User-agent") == "Wbreiler-Screenshot-Uploader/1.0"
        assert b'name="file"' in request.data and b"png-content" in request.data
        assert request.get_header("X-zipline-extensionless") == "true"
        assert timeout == 60
        return Response()

    with patch.object(client.urllib.request, "urlopen", send):
        assert client.upload(path, "private-token") == Response.url
        Response.url = "https://unexpected.example/image.png"
        try:
            client.upload(path, "private-token")
            raise AssertionError("Unexpected host was accepted")
        except ValueError:
            pass

print("Multipart upload, URL parsing, and unexpected-host rejection passed")
