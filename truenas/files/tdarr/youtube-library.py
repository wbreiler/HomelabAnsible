"""Reconcile one archive mount and one library through TrueNAS and Tdarr APIs."""

import argparse
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.request


def command(*args):
    return subprocess.check_output(args, text=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--server-path", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    assert args.dataset.startswith("gaia/Archive/")
    database = Path(args.server_path) / "Tdarr/DB2/SQL/database.db"
    # Follow the node's configured key when several keys exist during rotation.
    node_config = Path(args.server_path).parent / "config/Tdarr_Node_Config.json"
    key = json.loads(node_config.read_text())["apiKey"]

    def api(endpoint, data=None):
        request = urllib.request.Request(
            args.url + "/api/v2/" + endpoint,
            data=json.dumps({"data": data}).encode() if data is not None else None,
            headers={"Content-Type": "application/json", "x-api-key": key},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            if not payload:
                return None
            try:
                return json.loads(payload)
            except ValueError:
                return payload.decode()

    def crud(collection, mode, doc_id="", obj=None):
        return api("cruddb", {"collection": collection, "mode": mode,
                              "docID": doc_id, "obj": obj or {}})

    libraries = crud("LibrarySettingsJSONDB", "getAll")
    flows = crud("FlowsJSONDB", "getAll")
    def gpu_node():
        nodes = api("get-nodes")
        return next(n for n in nodes.values() if n.get("workerLimits", {}).get("transcodegpu", 0) > 0)

    node = gpu_node()
    template = next(lib for lib in libraries if lib["name"] == "Movies")
    source_flow = next(flow for flow in flows if flow["_id"] == template["flowId"])
    flow = copy.deepcopy(source_flow)
    flow.update(_id="youtubeAv1", name="YouTube AV1 - preserve all audio and subtitles")
    # Preserve untagged and non-English YouTube audio and captions.
    for plugin in flow["flowPlugins"]:
        if plugin["pluginName"] == "ffmpegCommandRemoveStreamByProperty":
            plugin["fpEnabled"] = False
    existing_library = next((lib for lib in libraries if lib["_id"] == "youtubeArchive"), None)
    library = copy.deepcopy(existing_library or template)
    library.update(_id="youtubeArchive", name="YouTube", folder="/youtube",
                   cache="/temp/youtube", flowId="youtubeAv1", priority=3,
                   processLibrary=True, processTranscodes=True, processHealthChecks=True,
                   folderWatching=True, scanOnStart=True, holdNewFiles=True,
                   holdFor=300, holdForDisplayUnit="seconds",
                   containerFilter="mkv,mp4,webm,mov,m4v")
    if existing_library is None:
        library.update(createdAt=int(time.time() * 1000), totalHealthCheckCount=0,
                       totalTranscodeCount=0, sizeDiff=0, scanFound="Files found:0")
    current_flow = next((item for item in flows if item["_id"] == flow["_id"]), None)
    config = json.loads(command("midclt", "call", "app.config", "tdarr"))
    service = config["services"]["tdarr"]
    mount = f"/mnt/{args.dataset}:/youtube"
    volumes = service["volumes"]
    assert not any(v.endswith(":/youtube") and v != mount for v in volumes)
    mount_changed = mount not in volumes
    app_changed = mount_changed or service["environment"].get("startPaused") != "false"
    changed = app_changed or current_flow != flow or existing_library != library or node["nodePaused"]
    if args.check or not changed:
        print(json.dumps({"changed": changed, "mount_changed": mount_changed}))
        return

    backup = Path(args.server_path) / "Tdarr/Backups" / time.strftime("youtube-%Y%m%d-%H%M%S")
    backup.mkdir(mode=0o700)
    os.chmod(backup, 0o700)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "database.db") as target:
            source.backup(target)
    os.chmod(backup / "database.db", 0o600)
    (backup / "compose.json").write_text(json.dumps(config))
    os.chmod(backup / "compose.json", 0o600)
    if app_changed:
        processes = command("docker", "top", "tdarr", "-eo", "pid,comm").splitlines()[1:]
        assert not any(p.split()[-1] in ("ffmpeg", "HandBrakeCLI") for p in processes), "Wait for active transcodes before restarting Tdarr"
        # An app update can pull an untagged image. Preserve the running release.
        image_id = command("docker", "inspect", "tdarr", "--format", "{{.Image}}").strip()
        digests = json.loads(command("docker", "image", "inspect", image_id,
                                     "--format", "{{json .RepoDigests}}"))
        assert digests, "The current Tdarr image needs a repository digest"
        service["image"] = digests[0]
        if mount_changed:
            volumes.append(mount)
        service["environment"]["startPaused"] = "false"
        command("midclt", "call", "-j", "app.update", "tdarr",
                json.dumps({"custom_compose_config": config}))
        for attempt in range(60):
            try:
                node = gpu_node()
                break
            except (OSError, ValueError, StopIteration):
                time.sleep(2)
        else:
            raise RuntimeError("Tdarr API did not recover after its mount update")
    Path("/mnt/gaia/appdata/tdarr/transcode_cache/youtube").mkdir(exist_ok=True)
    for collection, desired, existing in [
        ("FlowsJSONDB", flow, current_flow),
        ("LibrarySettingsJSONDB", library, existing_library),
    ]:
        if desired != existing:
            crud(collection, "update" if existing else "insert", desired["_id"], desired)
        actual = crud(collection, "getById", desired["_id"])
        assert actual == desired, f"{collection} failed read-back verification"
    if node["nodePaused"]:
        api("update-node", {"nodeID": node["_id"], "nodeUpdates": {"nodePaused": False}})
    assert gpu_node()["nodePaused"] is False
    if existing_library != library or app_changed:
        api("toggle-folder-watch", {"auto": False, "folder": "/youtube",
                                     "dbID": library["_id"], "status": True})
        api("scan-files", {"scanConfig": {"dbID": library["_id"],
                                           "arrayOrPath": "/youtube", "mode": "scanFindNew"}})
    print(json.dumps({"changed": True, "backup": str(backup)}))


if __name__ == "__main__":
    main()
