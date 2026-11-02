#!/usr/bin/python3
"""Guest-side installers for applications with custom update layouts.

The host supplies verified artifacts only after a successful PBS backup.
No guest configuration or credential is returned to the host.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def health(url):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(5)
    raise RuntimeError('application health check failed')


def replace_with_link(path, target, version):
    old = path.with_name(path.name + '.pre-auto-' + version)
    if old.exists() or old.is_symlink():
        raise RuntimeError('previous release backup exists; inspect before retrying')
    if path.exists() or path.is_symlink():
        path.rename(old)
    try:
        path.symlink_to(target, target_is_directory=True)
    except OSError:
        if old.exists() or old.is_symlink():
            old.rename(path)
        raise


def extract_source(source, root):
    unpacked = root / 'source'
    unpacked.mkdir()
    with tarfile.open(source) as archive_file:
        archive_file.extractall(unpacked, filter='data')
    entries = list(unpacked.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise RuntimeError('unexpected source archive layout')
    return entries[0]


def main():
    os.environ['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    app, version, archive = sys.argv[1:]
    if app not in {'homelable', 'nginx_proxy_manager', 'sabnzbd', 'open_webui', 'netboot_xyz', 'librespeed'}:
        raise ValueError('unsupported native application')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,3}', version):
        raise ValueError('invalid version')
    source = Path(archive)
    parent = Path('/opt/homelab-app-releases') / app
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix=version + '-', dir=parent))
    if app == 'open_webui':
        tool = Path('/root/.local/share/uv/tools/open-webui')
        base_python = subprocess.check_output([str(tool / 'bin/python'), '-c', 'import sys; print(sys._base_executable)'], text=True).strip()
        uv = shutil.which('uv') or '/root/.local/bin/uv'
        env = {**os.environ, 'UV_TOOL_DIR': str(root), 'UV_TOOL_BIN_DIR': str(root / 'bin')}
        run(uv, 'tool', 'install', '--python', base_python,
            'open-webui[all] @ ' + source.as_uri(), env=env)
        run('systemctl', 'stop', 'open-webui')
        replace_with_link(tool, root / 'open-webui', version)
        run('systemctl', 'start', 'open-webui')
        health('http://127.0.0.1:8080/health')
        return
    if app == 'netboot_xyz':
        # The parent downloads and verifies both artifacts as one release.
        for name in ('netboot.xyz.efi', 'netboot.xyz.kpxe'):
            destination = Path('/srv/tftp') / name
            temporary = destination.with_suffix(destination.suffix + '.new')
            shutil.copyfile(source.parent / name, temporary)
            temporary.chmod(0o644)
            os.replace(temporary, destination)
        run('systemctl', 'is-active', '--quiet', 'tftpd-hpa')
        Path('/etc/netboot-xyz-version').write_text(version + '\n')
        return
    tree = extract_source(source, root)
    if app == 'homelable':
        for directory in (parent.parent, parent, root, tree.parent):
            directory.chmod(0o755)
        shutil.copy2('/opt/homelable/app/backend/.env', tree / 'backend/.env')
        run('chown', '-hR', 'homelable:homelable', str(tree))
        venv = root / 'venv'
        venv.mkdir()
        shutil.chown(venv, 'homelable', 'homelable')
        run('runuser', '-u', 'homelable', '--', 'python3', '-m', 'venv', str(venv))
        run('runuser', '-u', 'homelable', '--', str(venv / 'bin/pip'), 'install', '-r', str(tree / 'backend/requirements.txt'))
        for args in (('npm', 'ci'), ('npm', 'run', 'build')):
            run('runuser', '-u', 'homelable', '--', *args, cwd=tree / 'frontend')
        run('chmod', '-R', 'a+rX', str(tree / 'frontend/dist'))
        run('systemctl', 'stop', 'homelable')
        replace_with_link(Path('/opt/homelable/app'), tree, version)
        replace_with_link(Path('/opt/homelable/venv'), venv, version)
        run('systemctl', 'start', 'homelable')
        health('http://127.0.0.1:3000/api/v1/health')
        run('runuser', '-u', 'homelable', '--', 'sh', '-c', 'printf "%s\\n" "$1" > /opt/homelable/.ansible-version', 'version', version)
    elif app == 'sabnzbd':
        current = Path('/opt/sabnzbd')
        base_python = subprocess.check_output([str(current / 'venv/bin/python'), '-c', 'import sys; print(sys._base_executable)'], text=True).strip()
        uv = shutil.which('uv') or '/root/.local/bin/uv'
        run(uv, 'venv', '--python', base_python, str(tree / 'venv'))
        run(uv, 'pip', 'install', '--python', str(tree / 'venv/bin/python'), '-r', str(tree / 'requirements.txt'))
        run('systemctl', 'stop', 'sabnzbd')
        for config in current.glob('*.ini'):
            shutil.copy2(config, tree / config.name)
        replace_with_link(current, tree, version)
        run('systemctl', 'start', 'sabnzbd')
        health('http://127.0.0.1:7777/')
    elif app == 'nginx_proxy_manager':
        # OpenResty's worker must traverse the staged frontend path.
        for directory in (parent.parent, parent, root, tree.parent, tree):
            directory.chmod(0o755)
        backend, frontend = tree / 'backend', tree / 'frontend'
        for part in (backend, frontend):
            path = part / 'package.json'
            package = json.loads(path.read_text())
            package['version'] = version
            path.write_text(json.dumps(package))
        for script in (['yarn', 'install', '--frozen-lockfile', '--non-interactive'],
                       ['yarn', 'locale-compile'], ['yarn', 'build']):
            run(*script, cwd=frontend, env={**os.environ, 'NODE_OPTIONS': '--max-old-space-size=2048 --openssl-legacy-provider'})
        shutil.copytree(frontend / 'dist', backend / 'frontend', dirs_exist_ok=True)
        shutil.copytree(frontend / 'public/images', backend / 'frontend/images', dirs_exist_ok=True)
        backend.chmod(0o755)
        run('chmod', '-R', 'a+rX', str(backend / 'frontend'))
        shutil.copy2('/app/config/production.json', backend / 'config/production.json')
        (backend / 'config/default.json').unlink(missing_ok=True)
        run('yarn', 'install', '--frozen-lockfile', '--non-interactive', cwd=backend)
        run('systemctl', 'stop', 'npm')
        replace_with_link(Path('/app'), backend, version)
        run('systemctl', 'start', 'npm')
        health('http://127.0.0.1:81/api/')
        run('/usr/local/openresty/nginx/sbin/nginx', '-t')
        run('systemctl', 'is-active', '--quiet', 'openresty')
    elif app == 'librespeed':
        destination = Path('/var/www/librespeed-' + version)
        shutil.copytree(tree, destination)
        for directory, _, files in os.walk(destination):
            Path(directory).chmod(0o755)
            for name in files:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o644)
        interface = (destination / 'index-classic.html').read_text()
        settings = '\n'.join('s.setParameter(' + json.dumps(k) + ', ' + json.dumps(v) + ');' for k, v in (
            ('telemetry_level', 'off'), ('getIp_ispInfo', False), ('getIp_ispInfo_distance', False),
            ('overheadCompensationFactor', 1), ('time_auto', False)))
        old = 's.setParameter("telemetry_level", "basic");'
        if old not in interface:
            raise RuntimeError('upstream interface changed; LAN settings require review')
        (destination / 'index.html').write_text(interface.replace(old, settings))
        config = Path('/etc/nginx/sites-available/librespeed')
        original = config.read_text()
        updated, count = re.subn(r'root /var/www/librespeed-[0-9.]+;', 'root ' + str(destination) + ';', original)
        if count != 1:
            raise RuntimeError('unexpected LibreSpeed nginx configuration')
        config.with_name('librespeed.pre-auto-' + version).write_text(original)
        config.write_text(updated)
        try:
            run('nginx', '-t')
        except subprocess.CalledProcessError:
            config.write_text(original)
            raise
        run('systemctl', 'reload', 'nginx')
        for endpoint in ('/', '/speedtest.js', '/backend/empty.php'):
            health('http://127.0.0.1' + endpoint)
    else:
        raise ValueError('unsupported native application')


if __name__ == '__main__':
    main()
