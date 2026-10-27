#!/usr/bin/env python3
"""Provision one new guest with Terraform, then configure Gatus through Ansible."""

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]
APPS = {"gatus": ("gatus-guests.yml", "gatus_guests")}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    temporary.replace(path)


def validate(profile):
    if not isinstance(profile, dict):
        raise ValueError("The profile must be a JSON object")
    allowed = {"name", "kind", "app", "vm_id", "node_name", "datastore_id", "template_file_id",
               "iso_filename", "os", "bridge", "vlan_id", "ipv4_address", "gateway", "dns_servers",
               "ssh_public_key_file", "cores", "memory_mb", "disk_gb", "on_boot", "backup", "app_vars_file"}
    if set(profile) - allowed:
        raise ValueError("Unknown profile fields: " + ", ".join(sorted(set(profile) - allowed)))
    p = dict(app="gatus", datastore_id="local-zfs", bridge="vmbr0", cores=2, memory_mb=2048,
             on_boot=True, backup=True, os="debian")
    p.update(profile)
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,45}[a-z0-9]", p.get("name", "")):
        raise ValueError("Use a hostname with 2–47 lowercase letters, digits, or hyphens")
    if p.get("kind") not in {"lxc", "vm"} or p["app"] not in APPS:
        raise ValueError("Supported guest kinds: lxc/vm. Supported application: gatus")
    if p["os"] not in {"debian", "ubuntu"} or p["kind"] == "lxc" and p["os"] != "debian":
        raise ValueError("Gatus supports Debian LXCs and Debian/Ubuntu installation VMs")
    for field in ["node_name", "datastore_id", "bridge"]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,62}", p.get(field, "")):
            raise ValueError("Invalid " + field)
    for field, low, high in [("vlan_id", 1, 4094), ("cores", 1, 16), ("memory_mb", 2048, 32768)]:
        if type(p.get(field)) is not int or not low <= p[field] <= high:
            raise ValueError("Invalid " + field)
    if "vm_id" in p and (type(p["vm_id"]) is not int or not 100 <= p["vm_id"] <= 999999999):
        raise ValueError("Invalid vm_id")
    p.setdefault("disk_gb", 8 if p["kind"] == "lxc" else 24)
    if type(p["disk_gb"]) is not int or not (8 if p["kind"] == "lxc" else 24) <= p["disk_gb"] <= 1024:
        raise ValueError("Invalid disk_gb")
    for field in ["on_boot", "backup"]:
        if type(p[field]) is not bool:
            raise ValueError(field + " must be a boolean")
    address = ipaddress.IPv4Interface(p["ipv4_address"])
    gateway = ipaddress.IPv4Address(p["gateway"])
    if gateway not in address.network or address.ip in {gateway, address.network.network_address, address.network.broadcast_address}:
        raise ValueError("Invalid guest address or gateway")
    if not p.get("dns_servers"):
        raise ValueError("At least one IPv4 DNS server is required")
    for server in p["dns_servers"]:
        ipaddress.IPv4Address(server)
    key = Path(p["ssh_public_key_file"]).expanduser().resolve()
    public_key = key.read_text().strip()
    if not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+=*(?: [^\r\n]*)?", public_key):
        raise ValueError("Supply a single public SSH key, never a private key")
    p["ssh_public_key_file"] = str(key)
    if p["kind"] == "lxc":
        if not re.fullmatch(r"[A-Za-z0-9_.-]+:vztmpl/[A-Za-z0-9_.-]+", p.get("template_file_id", "")):
            raise ValueError("Use an existing Debian template_file_id")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.iso", p.get("iso_filename", "")):
        raise ValueError("Use an existing pinned iso_filename")
    if p.get("app_vars_file"):
        p["app_vars_file"] = str(Path(p["app_vars_file"]).expanduser().resolve())
        variables = json.loads(Path(p["app_vars_file"]).read_text())
        if not isinstance(variables, dict) or any(not k.startswith("gatus_") or k == "gatus_guest_ssh" for k in variables):
            raise ValueError("Application variables must be a JSON object containing only Gatus settings")
    return p


def address(p):
    if p["kind"] == "lxc":
        return "proxmox_virtual_environment_container.application_" + p["name"].replace("-", "_")
    return 'proxmox_virtual_environment_vm.iso_installation[' + json.dumps(p["name"]) + ']'


def vm_spec(p):
    fields = ["vm_id", "node_name", "datastore_id", "os", "iso_filename", "bridge", "vlan_id", "ipv4_address",
              "gateway", "dns_servers", "ssh_public_key_file", "cores", "memory_mb", "disk_gb", "on_boot", "backup"]
    return dict({key: p[key] for key in fields}, firmware="uefi", secure_boot=True)


def lxc_config(p, bootstrap=False):
    resource = {
        "node_name": p["node_name"], "vm_id": p["vm_id"], "description": "Application guest owned by Terraform and configured by Ansible.",
        "unprivileged": True, "started": not bootstrap, "start_on_boot": p["on_boot"], "tags": ["terraform", "application"],
        "cpu": {"cores": p["cores"], "limit": p["cores"]}, "memory": {"dedicated": p["memory_mb"], "swap": 0},
        "disk": {"datastore_id": p["datastore_id"], "size": p["disk_gb"], "replicate": False},
        "operating_system": {"template_file_id": p["template_file_id"], "type": "debian"},
        "initialization": {"hostname": p["name"], "dns": {"servers": p["dns_servers"]},
                           "ip_config": {"ipv4": {"address": p["ipv4_address"], "gateway": p["gateway"]}},
                           "user_account": {"keys": [Path(p["ssh_public_key_file"]).read_text().strip()]}},
        "network_interface": [{"name": "eth0", "bridge": p["bridge"], "vlan_id": p["vlan_id"]}],
        "lifecycle": {"prevent_destroy": True, "ignore_changes": ["tags"]},
    }
    if bootstrap:
        # Provider 0.118.0 sends root-only flags with nesting. Bootstrap only the new, stopped LXC through Terraform.
        resource["provisioner"] = [{"local-exec": {
            "command": 'python3 "${path.module}/scripts/deploy_guest.py" --bootstrap-lxc',
            "environment": {"APPLICATION_GUEST": json.dumps(p)},
        }}]
    else:
        resource["features"] = {"nesting": True}
    return {"resource": {"proxmox_virtual_environment_container": {address(p).split(".", 1)[1]: resource}}}


def review_plan(plan, p, start=False):
    allowed = {address(p)}
    if p["kind"] == "vm":
        allowed |= {kind + '[' + json.dumps(p["name"]) + ']' for kind in [
            "terraform_data.install_identity", "terraform_data.install_media", "proxmox_virtual_environment_file.install_media", "terraform_data.installation_ready"]}
    if plan.get("errored") or plan.get("deferred_changes"):
        raise ValueError("Terraform plan is incomplete")
    for r in plan.get("resource_changes", []):
        change = r["change"]
        if change["actions"] == ["no-op"] or r["mode"] == "data" and change["actions"] == ["read"]:
            continue
        if r["address"] not in allowed:
            raise ValueError("Plan affects another resource: " + r["address"])
        if change["actions"] == ["create"] and not start:
            if r["address"] == address(p) and change["after"].get("vm_id") != p["vm_id"]:
                raise ValueError("Guest VMID does not match the profile")
            continue
        if start and r["address"] == address(p) and change["actions"] == ["update"]:
            before, after = change["before"], change["after"]
            differences = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
            if differences == {"started"} and before["started"] is False and after["started"] is True:
                continue
        raise ValueError("Refusing updates, replacements, or deletion: " + r["address"])


def reserved_vmids(exclude_installation=None):
    path = ROOT.parents[1] / "minecraft" / "ansible" / "servers.yml"
    reserved = {int(value) for value in re.findall(r"^\s*(?:vmid|vm_id):\s*['\"]?(\d+)", path.read_text(), re.MULTILINE)} if path.exists() else set()
    for variables in ROOT.glob("*.auto.tfvars.json"):
        for name, spec in json.loads(variables.read_text()).get("iso_installations", {}).items():
            if name != exclude_installation:
                reserved.add(spec["vm_id"])
    return reserved


def contains_ip(value, address):
    if isinstance(value, dict):
        return any(contains_ip(v, address) for v in value.values())
    if isinstance(value, list):
        return any(contains_ip(v, address) for v in value)
    if isinstance(value, str) and len(value) <= 50:
        try:
            return ipaddress.ip_interface(value).ip == address
        except ValueError:
            pass
    return False


def ssh_args():
    endpoint = urllib.parse.urlsplit(os.environ["PROXMOX_VE_ENDPOINT"])
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError("Use a trusted HTTPS Proxmox endpoint without credentials")
    return ["ssh", "-i", str(Path("~/.ssh/cluster.pub").expanduser()), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15", "root@" + endpoint.hostname]


def cluster_guests():
    return json.loads(subprocess.check_output(ssh_args() + ["pvesh get /cluster/resources --type vm --output-format json"], text=True))


def prepare_guest_recreation(p, directory):
    known_hosts = directory / "known_hosts"
    if known_hosts.exists():
        shutil.copy2(known_hosts, directory / "previous-guest-known_hosts")
        subprocess.run(["ssh-keygen", "-R", p["ipv4_address"].split("/")[0], "-f", str(known_hosts)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def prepare_vm_recreation(p, resources, directory):
    identity = next((r for r in resources if r["address"] == 'terraform_data.install_identity[' + json.dumps(p["name"]) + ']'), None)
    if not identity:
        return
    identifier = identity["values"]["id"]
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("Invalid installation identity")
    cache = ROOT / "artifacts" / "iso-install" / identifier
    verified = cache / "verified.json"
    if verified.exists():
        if json.loads(verified.read_text())["uuid"] != identifier:
            raise ValueError("Inconsistent installation identity cache")
        for name in ["verified.json", "known_hosts"]:
            source = cache / name
            if source.exists():
                shutil.copy2(source, directory / ("previous-install-" + name))
        # A reviewed new VM creation legitimately rotates host keys. The installer repins only after UUID and OS verification.
        verified.unlink()


def grant_new_guest_access(p):
    identity = os.environ["PROXMOX_VE_API_TOKEN"].split("=", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", identity):
        raise ValueError("Use a privilege-separated Proxmox API token")
    code = """import json,subprocess,sys
p=json.loads(sys.stdin.readline())
guests=json.loads(subprocess.check_output(['pvesh','get','/cluster/resources','--type','vm','--output-format','json'],text=True))
assert all(g['vmid']!=p['vm_id'] for g in guests)
roles=json.loads(subprocess.check_output(['pveum','role','list','--output-format','json'],text=True))
assert any(r['roleid']=='TerraformGuest' and 'VM.Allocate' in r['privs'] for r in roles)
path='/vms/'+str(p['vm_id'])
for flag,identity in [('--users',p['identity'].split('!')[0]),('--tokens',p['identity'])]:
 subprocess.run(['pveum','acl','modify',path,flag,identity,'--roles','TerraformGuest','--propagate','0'],check=True)
"""
    subprocess.run(ssh_args() + ["python3 -c " + shlex.quote(code)],
                   input=json.dumps({"vm_id": p["vm_id"], "identity": identity}) + "\n", text=True, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def bootstrap_lxc():
    p = validate(json.loads(os.environ["APPLICATION_GUEST"]))
    assert p["kind"] == "lxc"
    # Values travel on stdin. The fixed remote program validates identity before its one narrow write.
    code = '''import json,subprocess,sys
p=json.loads(sys.stdin.readline())
def api(*args):
 return json.loads(subprocess.check_output(['pvesh',*args,'--output-format','json'],text=True))
path='/nodes/'+p['node_name']+'/lxc/'+str(p['vm_id'])
c=api('get',path+'/config')
assert c['hostname']==p['name'] and c['unprivileged']==1
assert api('get',path+'/status/current')['status']=='stopped'
subprocess.run(['pvesh','set',path+'/config','--features','nesting=1'],check=True)
assert api('get',path+'/config')['features']=='nesting=1'
'''
    command = "python3 -c " + shlex.quote(code)
    subprocess.run(ssh_args() + [command], input=json.dumps(p) + "\n", text=True, check=True)


def socket_directory(directory):
    # macOS UNIX socket paths are short. Keep per-deployment SSH reuse outside the long repository path.
    suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:16]
    path = Path("/private/tmp" if sys.platform == "darwin" else "/tmp") / ("guest-ssh-" + suffix)
    if path.is_symlink():
        raise ValueError("SSH socket directory must not be a symlink")
    path.mkdir(mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("SSH socket directory must be private and owned by the current user")
    return path


def prime_lxc_network(p):
    # A reused address can retain the previous guest's MAC in gateway ARP. Probe from the new LXC before controller SSH.
    code = """import json,platform,shlex,subprocess,sys
p=json.loads(sys.stdin.readline())
path='/nodes/'+p['node_name']+'/lxc/'+str(p['vm_id'])
c=json.loads(subprocess.check_output(['pvesh','get',path+'/config','--output-format','json'],text=True))
assert c['hostname']==p['name'] and c['unprivileged']==1
command=['pct','exec',str(p['vm_id']),'--','ping','-c','1','-W','2',p['gateway']]
if platform.node().split('.')[0]!=p['node_name']:
 command=['ssh','-o','BatchMode=yes','root@'+p['node_name'],shlex.join(command)]
subprocess.run(command,check=False)
"""
    subprocess.run(ssh_args() + ["python3 -c " + shlex.quote(code)], input=json.dumps(p) + "\n", text=True,
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def inventory(p, directory):
    variables = {
        "terraform_guest_name": p["name"],
        "ansible_host": p["ipv4_address"].split("/")[0], "ansible_user": "root" if p["kind"] == "lxc" else "ansible",
        "ansible_ssh_private_key_file": p["ssh_public_key_file"], "ansible_python_interpreter": "/usr/bin/python3",
        "ansible_control_path": str(socket_directory(directory) / "%%C"),
        "ansible_ssh_common_args": "-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=" + shlex.quote(str(directory / "known_hosts")),
        "gatus_discord_webhook_url": "", "gatus_extra_endpoints": [{"name": "Local Gatus", "url": "http://127.0.0.1:{{ gatus_port }}/health"}],
    }
    return {"all": {"children": {APPS[p["app"]][1]: {"hosts": {p["name"].replace("-", "_"): variables}}}}}


def load_environment():
    if (ROOT / ".env").exists():
        result = subprocess.check_output(["bash", "-c", 'set -a; source "$1"; env -0', "deploy-guest", str(ROOT / ".env")])
        os.environ.update(part.decode().split("=", 1) for part in result.split(b"\0") if part)


def deploy(args):
    os.umask(0o077)
    source = args.profile.resolve()
    p = validate(json.loads(source.read_text()))
    load_environment()
    terraform = args.terraform or os.environ.get("TF_BIN") or shutil.which("terraform")
    if not terraform or not shutil.which("ansible-playbook"):
        raise ValueError("Install Terraform and Ansible, or set TF_BIN to the existing Terraform executable")
    directory = ROOT / "artifacts" / "deploy" / p["name"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / "artifacts" / "deploy.lock").open("w") as lock, (directory / "run.lock").open("w") as job_lock:
        try:
            fcntl.flock(job_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another workflow is active. Retry this command after its Terraform phase completes") from exc
        recorded = directory / "profile.json"
        if recorded.exists():
            previous = json.loads(recorded.read_text())
            p.setdefault("vm_id", previous["vm_id"])
            if {k:v for k,v in p.items() if k != "app_vars_file"} != {k:v for k,v in previous.items() if k != "app_vars_file"}:
                raise ValueError("Guest hardware is immutable in this creation workflow. Use a separately reviewed Terraform change")
        live = cluster_guests()
        if "vm_id" not in p:
            occupied = {g["vmid"] for g in live} | reserved_vmids()
            p["vm_id"] = next(v for v in range(100, 1000000) if v not in occupied)
        resource_address = address(p)

        def run(command, label, cwd=ROOT, suffix=".log"):
            with (directory / (label + suffix)).open("w") as log:
                result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(label + " failed. See the protected log: " + str(directory / (label + suffix)))

        run([terraform, "show", "-json"], "state-before", suffix=".json")
        state = json.loads((directory / "state-before.json").read_text())
        resources = state.get("values", {}).get("root_module", {}).get("resources", [])
        owned = next((r for r in resources if r["address"] == resource_address), None)
        if owned and not recorded.exists():
            raise ValueError("Existing guest was not created by this workflow. Refusing application changes")
        occupants = [g for g in live if g["vmid"] == p["vm_id"]]
        if occupants and (not owned or owned["values"].get("vm_id") != p["vm_id"] or occupants[0]["name"] != p["name"]):
            raise ValueError("VMID is already in use by another guest")
        if owned and not occupants:
            raise ValueError("Managed guest is missing. Refusing automatic recreation")
        if not owned:
            if p["vm_id"] in reserved_vmids(p["name"] if p["kind"] == "vm" else None):
                raise ValueError("VMID is reserved in a local deployment or retained installation profile")
            ip = ipaddress.ip_interface(p["ipv4_address"]).ip
            if any(contains_ip(r["values"], ip) for r in resources if r.get("type") in {"proxmox_virtual_environment_container", "proxmox_virtual_environment_vm"} and r["address"] != resource_address):
                raise ValueError("The IP address already appears in Terraform state")
            try:
                connection = socket.create_connection((str(ip), 22), timeout=3)
            except OSError:
                pass
            else:
                connection.close()
                raise ValueError("The requested IP already accepts SSH. Refusing to provision")
        print(f"Guest {p['name']}: {p['kind']} {p['vm_id']}, {p['ipv4_address']}. Reviewing Terraform plan.", flush=True)
        config = ROOT / ("application-" + p["name"] + ".local.tf.json") if p["kind"] == "lxc" else ROOT / "iso-install.auto.tfvars.json"
        original = config.read_bytes() if config.exists() else None
        applied = False
        try:
            bootstrap = p["kind"] == "lxc" and not owned
            if p["kind"] == "lxc":
                if original is not None and not recorded.exists():
                    raise ValueError("A local guest definition already exists outside this workflow")
                write_json(config, lxc_config(p, bootstrap=bootstrap))
            else:
                variables = json.loads(original or b"{}")
                installations = variables.setdefault("iso_installations", {})
                if p["name"] in installations:
                    existing = installations[p["name"]]
                    normalized = dict(cores=2, memory_mb=2048, disk_gb=24, on_boot=True, backup=True, firmware="bios", secure_boot=False)
                    normalized.update(existing)
                    normalized["ssh_public_key_file"] = str(Path(normalized["ssh_public_key_file"]).expanduser().resolve())
                    if any(normalized.get(k) != v for k, v in vm_spec(p).items()) or existing.get("username", "ansible") != "ansible":
                        raise ValueError("An installation entry already exists with different settings")
                else:
                    installations[p["name"]] = vm_spec(p)
                write_json(config, variables)

            def plan_and_apply(label, start=False):
                plan = directory / (label + ".tfplan")
                run([terraform, "plan", "-no-color", "-out=" + str(plan)], label + "-plan")
                run([terraform, "show", "-json", str(plan)], label + "-plan", suffix=".json")
                data = json.loads((directory / (label + "-plan.json")).read_text())
                review_plan(data, p, start=start)
                if not owned and not start and not any(r["address"] == resource_address and r["change"]["actions"] == ["create"]
                                                       for r in data.get("resource_changes", [])):
                    raise ValueError("The configuration did not declare the requested new guest")
                if not args.plan_only:
                    if not owned and not start:
                        grant_new_guest_access(p)
                        prepare_guest_recreation(p, directory)
                        if p["kind"] == "vm":
                            prepare_vm_recreation(p, resources, directory)
                    write_json(recorded, p)
                    nonlocal applied
                    applied = True
                    run([terraform, "apply", "-no-color", "-parallelism=2", str(plan)], label + "-apply")
                return data

            resuming_start = bool(owned and p["kind"] == "lxc" and not owned["values"]["started"])
            plan_and_apply("create", start=resuming_start)
            if args.plan_only:
                print("Plan passed the creation-only guard. Nothing was applied.")
                return
            if bootstrap:
                write_json(config, lxc_config(p))
                plan_and_apply("start", start=True)
            run([terraform, "plan", "-no-color", "-detailed-exitcode"], "final-plan")
            if p["kind"] == "lxc":
                prime_lxc_network(p)
            write_json(directory / "inventory.yml", inventory(p, directory))
            fcntl.flock(lock, fcntl.LOCK_UN)
            command = ["ansible-playbook", "-i", str(directory / "inventory.yml"), APPS[p["app"]][0]]
            if p.get("app_vars_file"):
                command += ["--extra-vars", "@" + p["app_vars_file"]]
            print("Terraform is converged. Waiting for SSH and configuring Gatus with Ansible.", flush=True)
            run(command, "ansible", ROOT.parents[1] / "proxmox")
            write_json(directory / "complete.json", {"name": p["name"], "kind": p["kind"], "vm_id": p["vm_id"], "app": p["app"], "status": "configured"})
            print(f"Complete: {p['name']} ({p['vm_id']}). Evidence: {directory}")
        finally:
            if not applied:
                if original is None:
                    config.unlink(missing_ok=True)
                else:
                    config.write_bytes(original)


def main():
    if sys.argv[1:] == ["--bootstrap-lxc"]:
        bootstrap_lxc()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="Private JSON guest profile, resolved from the caller's directory")
    parser.add_argument("--plan-only", action="store_true", help="Review the guarded creation plan without applying or configuring")
    parser.add_argument("--terraform", help="Terraform executable (defaults to TF_BIN or PATH)")
    args = parser.parse_args()
    try:
        deploy(args)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
