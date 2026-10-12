#!/usr/bin/python3
"""Capture a selected region, upload it, and copy its public URL."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

ENDPOINT = "https://i.wbreiler.com/api/upload"
TOKEN_FILE = Path.home() / ".config/zipline/token"


def upload(path, token):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="screenshot.png"\r\nContent-Type: image/png\r\n\r\n').encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(ENDPOINT, data=body, headers={
        "Authorization": token,
        "User-Agent": "Wbreiler-Screenshot-Uploader/1.0",
        "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        url = json.load(response)["files"][0]["url"]
    if not url.startswith("https://i.wbreiler.com/"):
        raise ValueError("Server returned an unexpected image URL")
    return url


def main():
    if TOKEN_FILE.stat().st_mode & 0o077:
        raise ValueError("Token permissions must be 0600")
    token = TOKEN_FILE.read_text().strip()
    if not token:
        raise ValueError("Upload token is empty")
    with tempfile.TemporaryDirectory(prefix="screenshot-") as directory:
        path = Path(directory) / "screenshot.png"
        subprocess.run(["/usr/sbin/screencapture", "-i", "-x", str(path)], check=True)
        if not path.exists():
            return  # Escape cancels without an upload.
        url = upload(path, token)
        subprocess.run(["/usr/bin/pbcopy"], input=url.encode(), check=True)
        print(url)
        subprocess.run(["/usr/bin/osascript", "-e",
                        'display notification "Image link copied to clipboard" with title "Screenshot uploaded"'],
                       check=False)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, urllib.error.URLError, subprocess.CalledProcessError) as error:
        print(f"Screenshot upload failed: {error}", file=sys.stderr)
        sys.exit(1)
