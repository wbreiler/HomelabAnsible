import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:3000"
try:
    with urllib.request.urlopen(base + "/api/setup") as response:
        first = json.load(response).get("firstSetup")
except urllib.error.HTTPError as error:
    if error.code != 403:
        raise
    first = False
if first:
    path = Path("/opt/zipline/admin.json")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump({"username": "wbreiler", "password": secrets.token_urlsafe(32)}, output)
    credentials = json.loads(path.read_text())
    request = urllib.request.Request(base + "/api/setup", data=json.dumps(credentials).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        assert json.load(response)["firstSetup"] is False
    print("created")
