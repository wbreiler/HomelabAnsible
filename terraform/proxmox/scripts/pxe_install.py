#!/usr/bin/env python3
"""Publish immutable network installers and verify their installed guests."""
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

import iso_install as iso

DEBIAN_BASE = 'https://deb.debian.org/debian/dists/trixie/main/installer-amd64/20250803+deb13u7/images/netboot/debian-installer/amd64/'
DEBIAN_FILES = {
    'linux': '2b2358b37674d2505350528875bb17afae2a36522a9e8a9417eaca65a7da0e08',
    'initrd.gz': '57303d157cffce3fa402301667fbc9b2280aa7372082b081e777375ae49da5f2',
}


def server(spec):
    value = spec['pxe_server']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', value['host']):
        raise ValueError('Invalid PXE SSH host')
    url = urllib.parse.urlsplit(value['http_url'])
    if url.scheme != 'http' or not url.hostname or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment or re.search(r'\s', value['http_url']):
        raise ValueError('Use a plain LAN HTTP origin for PXE')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', url.hostname):
        raise ValueError('Invalid PXE HTTP hostname')
    vmid = value.get('container_id')
    if vmid is not None and (type(vmid) is not int or not 100 <= vmid <= 999999999):
        raise ValueError('Invalid PXE container ID')
    key = Path(value['ssh_public_key_file']).expanduser()
    if not key.read_text().startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')):
        raise ValueError('PXE access requires a public key selector')
    return value['http_url'].rstrip('/')


def ssh(spec):
    server(spec)
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'ControlPath=none',
            '-o', 'StrictHostKeyChecking=accept-new', '-o', 'IdentitiesOnly=yes',
            '-i', str(Path(spec['pxe_server']['ssh_public_key_file']).expanduser())]


def remote(spec, command, data=None):
    if spec['pxe_server'].get('container_id') is not None:
        command = f' pct exec {spec["pxe_server"]["container_id"]} -- sh -c ' + shlex.quote(command)
    subprocess.run(ssh(spec) + ['root@' + spec['pxe_server']['host'], command],
                   input=data, text=True, check=True)


SYNC_LIBRARY = r'''
import hashlib,json,os,pathlib,re,sys,urllib.parse,urllib.request
spec=json.load(sys.stdin)
root=pathlib.Path('/srv/pxe/iso')
root.mkdir(parents=True,exist_ok=True)
def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
for name,checksum in spec['files'].items():
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.iso',name): raise ValueError('Invalid ISO filename')
    if not re.fullmatch(r'[a-f0-9]{64}',checksum): raise ValueError('Invalid ISO checksum')
    target=root/name
    if target.is_symlink(): raise ValueError('ISO path is a symlink')
    if target.exists():
        if digest(target)!=checksum: raise ValueError('Existing ISO checksum mismatch: '+name)
        print('Verified '+name,flush=True)
        continue
    temporary=root/('.'+name+'.partial')
    with urllib.request.urlopen(spec['base_url'].rstrip('/')+'/'+name,timeout=60) as response, temporary.open('wb') as output:
        while block:=response.read(4*1024*1024): output.write(block)
    if digest(temporary)!=checksum:
        temporary.unlink()
        raise ValueError('Downloaded ISO checksum mismatch: '+name)
    temporary.chmod(0o644)
    temporary.replace(target)
    print('Copied and verified '+name,flush=True)
'''


def sync_library(spec):
    server(spec)
    url = urllib.parse.urlsplit(spec['base_url'])
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Invalid ISO source origin')
    remote(spec, 'python3 -c ' + shlex.quote(SYNC_LIBRARY), json.dumps(spec))


def validate(spec):
    address = iso.validate(spec)
    server(spec)
    if spec.get('firmware') != 'uefi':
        raise ValueError('PXE installation requires UEFI x86-64')
    if spec['os'] == 'ubuntu' and spec.get('memory_mb', 0) < 8192:
        raise ValueError('Ubuntu PXE needs at least 8192 MiB for its live ISO and installer')
    return address


def payloads(spec, image_url):
    address = validate(spec)
    base = server(spec)
    url = f"{base}/install/{spec['uuid']}"
    files = iso.payloads(spec)
    bootstrap = files['/terraform/bootstrap.sh']
    args = 'console=ttyS0,115200n8'
    ip = f"ip={address.ip}::{spec['gateway']}:{address.netmask}:{spec['name']}::none"
    if spec['os'] == 'debian':
        # Replace the complete copy command, preserving its error handling and UUID guard.
        seed = files['preseed.cfg'].decode().replace('cp /cdrom/terraform/bootstrap.sh /target/tmp/terraform-bootstrap.sh', f'wget -O /target/tmp/terraform-bootstrap.sh {url}/bootstrap.sh')
        files = {'preseed.cfg': seed.encode(), 'bootstrap.sh': bootstrap}
        kernel, initrd = f'{image_url}/linux', f'{url}/initrd.gz'
        args += ' auto=true priority=critical'
    elif spec['os'] == 'ubuntu':
        data = json.loads(files['/autoinstall.yaml'])
        data['autoinstall']['late-commands'][0] = ['wget', '-O', '/target/tmp/terraform-bootstrap.sh', f'{url}/bootstrap.sh']
        files = {'user-data': ('#cloud-config\n' + json.dumps(data)).encode(),
                 'meta-data': f"instance-id: {spec['uuid']}\nlocal-hostname: {spec['name']}\n".encode(),
                 'bootstrap.sh': bootstrap}
        kernel, initrd = f'{image_url}/linux', f'{image_url}/initrd'
        args += f" {ip} autoinstall cloud-config-url=/dev/null url={base}/iso/{spec['iso_filename']} ds=nocloud-net;s={url}/"
    else:
        seed = files['/ks.cfg'].decode().replace('\ncdrom\n', f'\nurl --url={image_url}/repo\n')
        seed = seed.replace('cp /run/install/repo/terraform/bootstrap.sh /mnt/sysroot/tmp/terraform-bootstrap.sh', f'curl --fail --output /mnt/sysroot/tmp/terraform-bootstrap.sh {url}/bootstrap.sh')
        files = {'ks.cfg': seed.encode(), 'bootstrap.sh': bootstrap}
        kernel, initrd = f'{image_url}/repo/images/pxeboot/vmlinuz', f'{image_url}/repo/images/pxeboot/initrd.img'
        args += f' {ip} nameserver={spec["dns_servers"][0]} inst.repo={image_url}/repo inst.ks={url}/ks.cfg inst.text'
    script = f'''#!ipxe
iseq ${{uuid}} {spec['uuid']} || exit
shim {image_url}/shim.efi || goto failed
kernel {kernel} initrd=initrd {args} || goto failed
initrd --name initrd {initrd} || goto failed
boot || goto failed
:failed
echo Automatic installation failed. Check the PXE server.
sleep 10
exit
'''
    return files, script


def assets(spec, root):
    source = iso.source_iso(spec, root.parent / 'iso-install')
    # The Debian network initrd must match its network kernel, not the CD-ROM initrd.
    pin = spec['source_sha256'] + (json.dumps(DEBIAN_FILES, sort_keys=True) if spec['os'] == 'debian' else '')
    identity = hashlib.sha256(pin.encode()).hexdigest()
    published = root / 'images' / identity
    published.parent.mkdir(parents=True, exist_ok=True)
    with published.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (published / '.complete').exists():
            checksums = json.loads((published / '.complete').read_text())
            if not checksums or any(iso.digest(published / name) != checksum for name, checksum in checksums.items()):
                raise ValueError('Cached network installer checksum mismatch')
            return identity, published
        if published.exists():
            raise ValueError('Incomplete network installer cache requires inspection')
        with tempfile.TemporaryDirectory(dir=published.parent) as temporary:
            directory = Path(temporary)
            listing = iso.run(['xorriso', '-indev', str(source), '-find', '/', '-type', 'f', '-exec', 'echo', '--'])
            paths = re.findall(r"^'([^']+)'$", listing, re.M)
            shim = next(p for p in paths if p.lower() == '/efi/boot/bootx64.efi')
            iso.run(['xorriso', '-osirrox', 'on', '-indev', str(source), '-extract', shim, str(directory / 'shim.efi')])
            if spec['os'] == 'debian':
                if not spec['iso_filename'].startswith('debian-13.'):
                    raise ValueError('The pinned Debian network installer supports Debian 13 only')
                for name, checksum in DEBIAN_FILES.items():
                    target = directory / name
                    with urllib.request.urlopen(DEBIAN_BASE + name, timeout=60) as response, target.open('wb') as stream:
                        shutil.copyfileobj(response, stream)
                    if iso.digest(target) != checksum:
                        raise ValueError('Debian network installer checksum mismatch')
            elif spec['os'] == 'ubuntu':
                for source_path, name in [('/casper/vmlinuz', 'linux'), ('/casper/initrd', 'initrd')]:
                    iso.run(['xorriso', '-osirrox', 'on', '-indev', str(source), '-extract', source_path, str(directory / name)])
            else:
                iso.run(['xorriso', '-osirrox', 'on', '-indev', str(source), '-extract', '/', str(directory / 'repo')])
            checksums = {str(p.relative_to(directory)): iso.digest(p) for p in directory.rglob('*') if p.is_file()}
            (directory / '.complete').write_text(json.dumps(checksums, sort_keys=True) + '\n')
            directory.rename(published)
    return identity, published


def upload(spec, directory, destination):
    # No --delete: immutable source images and recovery artifacts must survive later changes.
    path = ['--rsync-path', f'pct exec {spec["pxe_server"]["container_id"]} -- rsync'] if spec['pxe_server'].get('container_id') is not None else []
    subprocess.run(['rsync', '-rlt', '--checksum', '--chmod=D755,F644', *path, '-e', shlex.join(ssh(spec)),
                    str(directory) + '/', 'root@' + spec['pxe_server']['host'] + ':' + destination + '/'], check=True)


def build(spec):
    validate(spec)
    root = Path(spec['output_iso']).parent.parent.parent / 'pxe'
    root.mkdir(parents=True, exist_ok=True)
    Path(spec['output_iso']).parent.mkdir(parents=True, exist_ok=True)
    identity, image = assets(spec, root)
    image_url = f'{server(spec)}/images/{identity}'
    files, script = payloads(spec, image_url)
    if spec['os'] == 'debian':
        files['initrd.gz'] = (image / 'initrd.gz').read_bytes() + gzip.compress(iso.newc('preseed.cfg', files.pop('preseed.cfg')), mtime=0)
    directory = root / spec['uuid']
    directory.mkdir(exist_ok=True)
    fingerprint = hashlib.sha256(script.encode() + b''.join(name.encode() + hashlib.sha256(content).digest() for name, content in sorted(files.items()))).hexdigest()
    manifest = directory / '.manifest'
    if manifest.exists() and manifest.read_text().strip() != fingerprint:
        raise ValueError('Existing PXE installation inputs changed. Use a new VM identity')
    for name, content in files.items():
        (directory / name).write_bytes(content)
    manifest.write_text(fingerprint + '\n')
    remote(spec, f'mkdir -p /srv/pxe/images/{identity} /srv/pxe/install/{spec["uuid"]}')
    upload(spec, image, f'/srv/pxe/images/{identity}')
    upload(spec, directory, f'/srv/pxe/install/{spec["uuid"]}')
    # Publish the entry point last. A partial upload must never start an installation.
    identifier = spec['uuid']
    remote(spec, f'cat > /srv/pxe/boot/{identifier}.tmp && '
           f'if test -e /srv/pxe/install/{identifier}/.installed; then '
           f'rm -f /srv/pxe/boot/{identifier}.tmp /srv/pxe/boot/{identifier}.ipxe; else '
           f'chmod 644 /srv/pxe/boot/{identifier}.tmp && mv /srv/pxe/boot/{identifier}.tmp /srv/pxe/boot/{identifier}.ipxe; fi', script)
    print(f'Published unattended {spec["os"]} PXE installer for {spec["name"]}', flush=True)


def wait(spec):
    validate(spec)
    iso.wait(spec)
    # An installed VM must never format its disk again if firmware later falls back to PXE.
    remote(spec, f'touch /srv/pxe/install/{spec["uuid"]}/.installed && rm -f /srv/pxe/boot/{spec["uuid"]}.ipxe')
    print('Retired the automatic PXE entry after installed-system verification', flush=True)


def rearm(spec):
    validate(spec)
    remote(spec, f'rm -f /srv/pxe/install/{spec["uuid"]}/.installed')
    build(spec)


if __name__ == '__main__':
    os.umask(0o077)
    specification = json.loads(os.environ['ISO_INSTALL_SPEC'])
    {'build': build, 'rearm': rearm, 'wait': wait, 'sync-library': sync_library}[sys.argv[1]](specification)
