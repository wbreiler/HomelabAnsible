#!/usr/bin/env python3
"""Build private boot media and verify a new installation; never control a console."""

import base64
import fcntl
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid


def validate(spec):
    if spec["os"] not in {"debian", "ubuntu", "fedora"}:
        raise ValueError("Supported profiles: Debian netinst, Ubuntu live-server, Fedora Server DVD")
    for key, pattern in [("name", r"[a-z][a-z0-9-]{0,61}[a-z0-9]"),
                         ("username", r"[a-z_][a-z0-9_-]{0,31}"),
                         ("iso_filename", r"[A-Za-z0-9][A-Za-z0-9_.-]*\.iso"),
                         ("source_sha256", r"[a-f0-9]{64}")]:
        if not re.fullmatch(pattern, spec[key]):
            raise ValueError(f"Invalid {key}")
    if spec["username"] == "root" or str(uuid.UUID(spec["uuid"])) != spec["uuid"]:
        raise ValueError("Use a non-root account and a canonical UUID")
    address = ipaddress.IPv4Interface(spec["ipv4_address"])
    gateway = ipaddress.IPv4Address(spec["gateway"])
    if address.ip in {address.network.network_address, address.network.broadcast_address, gateway} or gateway not in address.network:
        raise ValueError("Invalid guest address/gateway")
    if not spec["dns_servers"]:
        raise ValueError("At least one IPv4 DNS server is required")
    for server in spec["dns_servers"]:
        ipaddress.IPv4Address(server)
    public_key = spec["public_key"]
    if "\n" in public_key or "\r" in public_key:
        raise ValueError("SSH public keys must be a single line")
    fields = public_key.split()
    if len(fields) < 2 or fields[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
        raise ValueError("Supply an OpenSSH public key, never a private key")
    wire = base64.b64decode(fields[1], validate=True)
    length = struct.unpack(">I", wire[:4])[0]
    if wire[4:4 + length].decode() != fields[0]:
        raise ValueError("SSH key type does not match its encoded data")
    url = urllib.parse.urlsplit(spec["source_url"])
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Use an HTTP(S) ISO URL without credentials, queries, or fragments")
    return address


def digest(path, algorithm="sha256"):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def run(args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(result.stdout[-5000:])
    return result.stdout


def newc(name, content):
    """One root-owned initramfs file, followed by a cpio trailer."""
    result = bytearray()
    for filename, data, mode in [(name, content, 0o100600), ("TRAILER!!!", b"", 0)]:
        encoded = filename.encode() + b"\0"
        fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        result.extend(b"070701" + "".join(f"{n:08x}" for n in fields).encode() + encoded)
        result.extend(b"\0" * (-len(result) % 4))
        result.extend(data)
        result.extend(b"\0" * (-len(result) % 4))
    return bytes(result)


def bootstrap(spec):
    user = spec["username"]
    key = base64.b64encode((spec["public_key"] + "\n").encode()).decode()
    service = "sshd" if spec["os"] == "fedora" else "ssh"
    return f"""#!/bin/sh
set -eu
id {user} >/dev/null
install -d -m 0700 -o {user} -g {user} /home/{user}/.ssh
printf '%s' '{key}' | base64 -d > /home/{user}/.ssh/authorized_keys
chown {user}:{user} /home/{user}/.ssh/authorized_keys
chmod 0600 /home/{user}/.ssh/authorized_keys
install -d -m 0755 /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\\nPermitRootLogin no\\n' > /etc/ssh/sshd_config.d/00-terraform-iso.conf
printf '{user} ALL=(ALL) NOPASSWD: ALL\\n' > /etc/sudoers.d/90-terraform-iso
chmod 0440 /etc/sudoers.d/90-terraform-iso
visudo -cf /etc/sudoers.d/90-terraform-iso
passwd -l root >/dev/null
passwd -l {user} >/dev/null
if command -v restorecon >/dev/null; then restorecon -RF /home/{user}/.ssh; fi
systemctl enable {service} qemu-guest-agent
install -d -m 0700 /var/lib/terraform-iso-install
printf '%s\\n' '{spec['uuid']}' > /var/lib/terraform-iso-install/complete
"""


def payloads(spec):
    address = validate(spec)
    guard = f'test "$(tr A-Z a-z < /sys/class/dmi/id/product_uuid)" = "{spec["uuid"]}"'
    files = {"/terraform/bootstrap.sh": bootstrap(spec).encode()}
    if spec["os"] == "debian":
        seed = Path(__file__).resolve().parents[1].joinpath("debian-preseed.cfg.example").read_text()
        values = {"ADDRESS": str(address.ip), "NETMASK": str(address.netmask), "GATEWAY": spec["gateway"],
                  "DNS": " ".join(spec["dns_servers"]), "NAME": spec["name"], "USERNAME": spec["username"],
                  "VM_UUID": spec["uuid"]}
        for key, value in values.items():
            seed = seed.replace("@" + key + "@", value)
        if re.search(r"@[A-Z_]+@", seed):
            raise ValueError("Unresolved Debian preseed placeholder")
        files["preseed.cfg"] = seed.encode()
    elif spec["os"] == "ubuntu":
        files["/autoinstall.yaml"] = json.dumps({"autoinstall": {
            "version": 1, "locale": "en_US.UTF-8", "keyboard": {"layout": "us"},
            "refresh-installer": {"update": False}, "apt": {"geoip": False},
            "early-commands": [["/bin/sh", "-ec", guard]],
            "identity": {"hostname": spec["name"], "username": spec["username"], "password": "!"},
            "ssh": {"install-server": True, "allow-pw": False, "authorized-keys": [spec["public_key"]]},
            "network": {"version": 2, "ethernets": {"install": {"match": {"name": "e*"},
                "dhcp4": False, "addresses": [spec["ipv4_address"]],
                "routes": [{"to": "default", "via": spec["gateway"]}],
                "nameservers": {"addresses": spec["dns_servers"]}}}},
            "storage": {"layout": {"name": "direct", "match": {"path": "/dev/sda"}}, "swap": {"size": 0}},
            "packages": ["openssh-server", "qemu-guest-agent", "sudo", "python3"],
            "late-commands": [["cp", "/cdrom/terraform/bootstrap.sh", "/target/tmp/terraform-bootstrap.sh"],
                ["curtin", "in-target", "--target=/target", "--", "/bin/sh", "/tmp/terraform-bootstrap.sh"],
                ["rm", "/target/tmp/terraform-bootstrap.sh"]], "shutdown": "reboot"
        }}, indent=2).encode()
    else:
        files["/ks.cfg"] = f"""text
cdrom
lang en_US.UTF-8
keyboard us
timezone UTC --utc
network --device=link --bootproto=static --ip={address.ip} --netmask={address.netmask} --gateway={spec['gateway']} --nameserver={','.join(spec['dns_servers'])} --hostname={spec['name']} --activate
rootpw --lock
user --name={spec['username']} --password=!* --iscrypted --groups=wheel
firewall --enabled --service=ssh
selinux --enforcing
services --enabled=sshd,qemu-guest-agent
firstboot --disable
ignoredisk --only-use=sda
zerombr
clearpart --all --initlabel --drives=sda
autopart --type=plain --fstype=ext4 --nohome --noswap
bootloader --location=mbr --boot-drive=sda
reboot
%pre --erroronfail --interpreter=/bin/sh
set -eu
{guard}
%end
%packages --excludedocs
@core
openssh-server
qemu-guest-agent
sudo
python3
%end
%post --nochroot --erroronfail --interpreter=/bin/sh
set -eu
cp /run/install/repo/terraform/bootstrap.sh /mnt/sysroot/tmp/terraform-bootstrap.sh
chroot /mnt/sysroot /bin/sh /tmp/terraform-bootstrap.sh
rm /mnt/sysroot/tmp/terraform-bootstrap.sh
%end
""".encode()
    return files


def source_iso(spec, root):
    cache = root / "sources"
    cache.mkdir(mode=0o700, exist_ok=True)
    path = cache / (spec["source_sha256"] + ".iso")
    with (cache / (spec["source_sha256"] + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError("Source cache cannot be a symlink")
        if not path.exists():
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    with urllib.request.urlopen(spec["source_url"], timeout=60) as response:
                        shutil.copyfileobj(response, stream)
                    stream.close()
                    if digest(temporary) != spec["source_sha256"]:
                        raise ValueError("Source ISO SHA256 mismatch")
                    temporary.rename(path)
                finally:
                    temporary.unlink(missing_ok=True)
        if digest(path) != spec["source_sha256"]:
            raise ValueError("Cached source ISO SHA256 mismatch")
    return path


def build(spec):
    validate(spec)
    if not shutil.which("xorriso"):
        raise RuntimeError("Install xorriso on the Terraform controller before applying")
    output = Path(spec["output_iso"])
    if output.name != "autoinstall.iso" or output.parent.name != spec["uuid"]:
        raise ValueError("Output must be a UUID-scoped autoinstall.iso")
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    manifest = output.with_suffix(".json")
    if output.is_symlink() or manifest.is_symlink():
        raise ValueError("Installation artifacts cannot be symlinks")
    creation_keys = ["os", "name", "username", "uuid", "ipv4_address", "gateway", "dns_servers", "public_key", "source_sha256"]
    fingerprint = hashlib.sha256(json.dumps({k: spec[k] for k in creation_keys}, sort_keys=True).encode()).hexdigest()
    if output.exists():
        prior = json.loads(manifest.read_text())
        if prior["spec_sha256"] != fingerprint or prior["image_sha256"] != digest(output):
            raise ValueError("Existing installation media changed; use a new VM UUID instead of overwriting it")
        print(f"Verified existing private {spec['os']} media", flush=True)
        return
    source = source_iso(spec, output.parent.parent)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        work = Path(tmp)
        mapped = payloads(spec)
        if spec["os"] == "debian":
            original = work / "original-initrd.gz"
            run(["xorriso", "-osirrox", "on", "-indev", str(source), "-extract", "/install.amd/initrd.gz", str(original)])
            mapped["/install.amd/initrd.gz"] = original.read_bytes() + gzip.compress(newc("preseed.cfg", mapped.pop("preseed.cfg")), mtime=0)
            kernel, initrd = "/install.amd/vmlinuz", "/install.amd/initrd.gz"
            args = "auto=true priority=critical console=ttyS0,115200n8 --- console=ttyS0,115200n8"
        elif spec["os"] == "ubuntu":
            kernel, initrd = "/casper/vmlinuz", "/casper/initrd"
            args = "autoinstall console=ttyS0,115200n8 --- console=ttyS0,115200n8"
        else:
            kernel, initrd = "/images/pxeboot/vmlinuz", "/images/pxeboot/initrd.img"
            with source.open("rb") as stream:
                stream.seek(16 * 2048 + 40)
                label = stream.read(32).decode("ascii").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
                raise ValueError("Unsupported Fedora ISO volume label")
            args = f"inst.stage2=hd:LABEL={label} inst.ks=cdrom:/ks.cfg inst.text console=ttyS0,115200n8"
        listing = run(["xorriso", "-indev", str(source), "-find", "/", "-type", "f", "-exec", "echo", "--"])
        paths = set(re.findall(r"^'([^']+)'$", listing, re.M))
        if not {kernel, initrd} <= paths or (spec["os"] == "fedora" and "/.treeinfo" not in paths):
            raise ValueError("Source does not match the selected server installer profile")
        grub = f"set default=0\nset timeout=1\nmenuentry 'Automatic {spec['os']} installation' {{\n linux {kernel} {args}\n initrd {initrd}\n}}\n".encode()
        syslinux = f"default automatic\nprompt 0\ntimeout 10\nlabel automatic\n kernel {kernel}\n append initrd={initrd} {args}\n".encode()
        boot_paths = {"/boot/grub/grub.cfg", "/boot/grub/loopback.cfg", "/EFI/BOOT/grub.cfg", "/boot/grub2/grub.cfg"} & paths
        for path in boot_paths:
            mapped[path] = grub
        for path in {"/isolinux/isolinux.cfg"} & paths:
            mapped[path] = syslinux
        if not boot_paths and "/isolinux/isolinux.cfg" not in paths:
            raise ValueError("No supported BIOS/UEFI boot configuration found")
        if "/md5sum.txt" in paths:
            sums = work / "md5sum.txt"
            run(["xorriso", "-osirrox", "on", "-indev", str(source), "-extract", "/md5sum.txt", str(sums)])
            lines = [line for line in sums.read_text().splitlines() if line.strip() and line.split(maxsplit=1)[-1].lstrip("*").removeprefix(".") not in mapped]
            lines += [f"{hashlib.md5(data).hexdigest()}  .{path}" for path, data in mapped.items()]
            mapped["/md5sum.txt"] = ("\n".join(lines) + "\n").encode()
        temporary = work / "result.iso"
        args = ["xorriso", "-indev", str(source), "-outdev", str(temporary)]
        for i, (destination, data) in enumerate(mapped.items()):
            p = work / f"payload-{i}"
            p.write_bytes(data)
            p.chmod(0o600)
            args += ["-map", str(p), destination]
        # Replay after mapping so hybrid BIOS/UEFI boot records retain the source layout.
        run(args + ["-boot_image", "any", "replay", "-commit", "-end"])
        temporary.chmod(0o600)
        result = {"spec_sha256": fingerprint, "source_sha256": spec["source_sha256"], "image_sha256": digest(temporary)}
        temporary.rename(output)
        manifest.write_text(json.dumps(result, indent=2) + "\n")
        manifest.chmod(0o600)
    print(f"Built private {spec['os']} media; original ISO unchanged", flush=True)


VERIFY = r'''
import json, pathlib, platform, subprocess, sys
def run(args):
    return subprocess.check_output(args, text=True).strip()
policy = run(['sshd', '-T'])
result = {
    'uuid': pathlib.Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower(),
    'os': platform.freedesktop_os_release()['ID'],
    'version': platform.freedesktop_os_release()['VERSION_ID'],
    'marker': pathlib.Path('/var/lib/terraform-iso-install/complete').read_text().strip(),
    'root': run(['findmnt', '-n', '-o', 'SOURCE', '/']),
    'agent': run(['systemctl', 'is-active', 'qemu-guest-agent']),
    'failed_units': run(['systemctl', '--failed', '--no-legend', '--plain']),
    'password_auth_disabled': 'passwordauthentication no' in policy,
    'root_ssh_disabled': 'permitrootlogin no' in policy,
    'user_locked': run(['passwd', '-S', sys.argv[1]]).split()[1] in ['L', 'LK'],
    'root_locked': run(['passwd', '-S', 'root']).split()[1] in ['L', 'LK'],
}
print(json.dumps(result))
'''


def wait(spec, timeout=1800):
    address = validate(spec)
    directory = Path(spec["output_iso"]).parent
    known_hosts = directory / "known_hosts"
    verified = directory / "verified.json"
    pinned = verified.exists()
    if pinned and (not known_hosts.exists() or json.loads(verified.read_text())["uuid"] != spec["uuid"]):
        raise RuntimeError("Verified SSH identity cache is missing or inconsistent")
    deadline = time.monotonic() + timeout
    last = "SSH not ready"
    while time.monotonic() < deadline:
        probe = None
        if not pinned:
            # Ubuntu's live installer has a different key. Pin only the verified installed OS.
            fd, name = tempfile.mkstemp(prefix="host-key-probe-", dir=directory)
            os.close(fd)
            probe = Path(name)
        try:
            try:
                result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=no", "-o", "ControlPath=none",
                    "-o", "IdentitiesOnly=yes", "-i", os.path.expanduser(spec["ssh_public_key_file"]),
                    "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={probe or known_hosts}",
                    f"{spec['username']}@{address.ip}", "sudo -n python3 -c " + shlex.quote(VERIFY) + " " + shlex.quote(spec["username"])],
                    capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess([], 255, "", "SSH verification timed out")
            if result.returncode == 0:
                evidence = json.loads(result.stdout)
                if evidence["uuid"] != spec["uuid"]:
                    raise RuntimeError("SSH reached another machine; refusing to accept this installation")
                if (evidence["marker"] == spec["uuid"] and evidence["os"] == spec["os"] and evidence["root"].startswith("/dev/")
                    and not evidence["root"].startswith("/dev/loop") and evidence["agent"] == "active" and not evidence["failed_units"]
                    and all(evidence[k] for k in ["password_auth_disabled", "root_ssh_disabled", "user_locked", "root_locked"])):
                    if probe:
                        if not probe.stat().st_size:
                            raise RuntimeError("SSH did not record an installed-system host key")
                        probe.replace(known_hosts)
                    verified.write_text(json.dumps(evidence, indent=2) + "\n"); verified.chmod(0o600)
                    print(f"Verified automatic {spec['os']} {evidence['version']} installation for {spec['name']}", flush=True)
                    return
                last = "Installed OS has not passed all health/account checks"
            else:
                last = "SSH or installation completion marker not ready"
        finally:
            if probe:
                probe.unlink(missing_ok=True)
        print(f"Waiting for {spec['name']}: {last}", flush=True)
        time.sleep(15)
    raise TimeoutError(f"Installation did not pass verification within {timeout} seconds: {last}")


if __name__ == "__main__":
    os.umask(0o077)
    specification = json.loads(os.environ["ISO_INSTALL_SPEC"])
    if sys.argv[1:] == ["build"]:
        build(specification)
    elif sys.argv[1:] == ["wait"]:
        wait(specification)
    else:
        raise SystemExit("Usage: iso_install.py build|wait (ISO_INSTALL_SPEC environment required)")
