"""Offline regression checks. Uses the Python environment that runs Ansible."""
import os
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import tempfile
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


class MacDevTests(unittest.TestCase):
    def test_main_preserves_dev_sleep_policy(self):
        task = next(t for t in load('roles/mac_main/tasks/macos_defaults.yml')
                    if t['name'] == 'Set system sleep to 1 minute')
        env = jinja2.Environment()
        for profiles, marker, expected in [(['main'], False, True),
                                          (['main', 'dev'], False, False),
                                          (['main'], True, False)]:
            with self.subTest(profiles=profiles, marker=marker):
                values = dict(mac_profiles=profiles,
                              mac_main_dev_marker={'stat': {'exists': marker}})
                self.assertEqual(all(env.compile_expression(c)(**values)
                                     for c in task['when']), expected)

    def test_dev_power_detects_convergence(self):
        task = next(t for t in load('roles/mac_dev/tasks/remote_access.yml')[0]['block']
                    if t['name'] == 'Keep development tasks available on AC power')
        env = jinja2.Environment()
        env.tests['search'] = lambda value, pattern: bool(re.search(pattern, value))
        condition = env.compile_expression(task['when'])
        self.assertFalse(condition(mac_dev_ac_power='\n sleep 0 (sleep prevented by powerd)\n womp 1\n autorestart 1\n'))
        for setting in ['sleep', 'womp', 'autorestart']:
            with self.subTest(setting=setting):
                power = '\n sleep 0\n womp 1\n autorestart 1\n'
                power = power.replace(setting + (' 0' if setting == 'sleep' else ' 1'),
                                      setting + (' 1' if setting == 'sleep' else ' 0'))
                self.assertTrue(condition(mac_dev_ac_power=power))

    def test_startup_opens_the_installed_app_after_login(self):
        agent = plistlib.loads((ROOT / 'files/com.wbreiler.codex-desktop.plist').read_bytes())
        packages = load('roles/mac_dev/defaults/main.yml')['mac_dev_casks']
        self.assertIn('chatgpt', packages)
        self.assertIn('codex', packages)
        self.assertEqual(agent['ProgramArguments'], ['/usr/bin/open', '-g', '-a', '/Applications/ChatGPT.app'])
        self.assertEqual(agent['LimitLoadToSessionType'], 'Aqua')
        self.assertTrue(agent['RunAtLoad'])
        self.assertNotIn('KeepAlive', agent)  # open exits immediately. Do not create a restart loop.

    def test_only_valid_public_keys_are_distributed(self):
        keys = ROOT / 'files/ssh_public_keys'
        self.assertEqual(len(list(keys.iterdir())), 6)
        for key in keys.iterdir():
            with self.subTest(key=key.name):
                self.assertEqual(key.suffix, '.pub')
                self.assertEqual(len(key.read_text().splitlines()), 1)
                subprocess.run(['/usr/bin/ssh-keygen', '-lf', str(key)], check=True, capture_output=True)
        selected = load('roles/mac_dev/defaults/main.yml')['mac_dev_authorized_key_files']
        self.assertEqual(selected, ['cluster.pub'])
        config = (ROOT / 'files/ssh_config').read_text()
        for name in re.findall(r'IdentityFile ~/.ssh/(\S+)', config):
            self.assertTrue((keys / name).is_file(), name)

    def test_ssh_preserves_forwarded_agent_without_bitwarden(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = dict(os.environ, HOME=directory, SSH_AUTH_SOCK=str(home / 'forwarded.sock'))
            # Isolate the socket lookup from any real Bitwarden session.
            config = home / 'config'
            config.write_text((ROOT / 'files/ssh_config').read_text().replace(
                'test -S ~/.bitwarden-ssh-agent.sock',
                f'test -S {home}/.bitwarden-ssh-agent.sock'))
            command = ['/usr/bin/ssh', '-G', '-F', str(config), 'github.com']
            before = subprocess.run(command, env=env, check=True, capture_output=True, text=True).stdout
            self.assertFalse(any(line.startswith('identityagent ') for line in before.splitlines()))
            with socket.socket(socket.AF_UNIX) as agent:
                agent.bind(str(home / '.bitwarden-ssh-agent.sock'))
                after = subprocess.run(command, env=env, check=True, capture_output=True, text=True).stdout
                selected = [line for line in after.splitlines() if line.startswith('identityagent ')]
                self.assertEqual(len(selected), 1)
                self.assertTrue(selected[0].endswith('/.bitwarden-ssh-agent.sock'))

    def test_ssh_tasks_preserve_existing_keys_and_converge(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.ssh').mkdir()
            existing = (ROOT / 'files/ssh_public_keys/github.pub').read_text()
            authorized = home / '.ssh/authorized_keys'
            authorized.write_text(existing)
            play = [{
                'name': 'Exercise SSH tasks in a temporary home',
                'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                'vars': {'home_dir': directory, 'mac_dev_authorized_key_files': ['cluster.pub']},
                'tasks': [{'ansible.builtin.import_tasks': str(ROOT / 'roles/mac_dev/tasks/ssh.yml')}],
            }]
            # playbook_dir must be mac/ so these are the actual role source paths.
            with tempfile.NamedTemporaryFile(mode='w', dir=ROOT, prefix='.ssh-test-', suffix='.yml') as harness:
                harness.write(yaml.safe_dump(play))
                harness.flush()
                command = ['ansible-playbook', harness.name, '-i', 'localhost,']
                first = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                second = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertRegex(second.stdout, r'changed=0\s')
            self.assertIn(existing.strip(), authorized.read_text())
            self.assertIn((ROOT / 'files/ssh_public_keys/cluster.pub').read_text().strip(), authorized.read_text())
            self.assertEqual(authorized.stat().st_mode & 0o777, 0o600)
            self.assertEqual((home / '.ssh/sockets').stat().st_mode & 0o777, 0o700)

    def test_readiness_rejects_incomplete_installations(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            tools = home / 'bin'
            tools.mkdir()
            app = home / 'ChatGPT.app'
            app.mkdir()
            (home / '.ssh').mkdir()
            (home / '.ssh/authorized_keys').write_text('fixture public key\n')
            source = (ROOT / 'files/mac-dev-check.sh').read_text()
            source = source.replace('/Applications/ChatGPT.app', str(app))
            source = source.replace('export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"',
                                    f'export PATH="{tools}:/usr/bin:/bin"')
            for tool in ['git', 'gh', 'cmake', 'ninja', 'node', 'uv', 'ansible', 'ansible-lint',
                         'codex', 'launchctl', 'dseditgroup', 'ssh-keygen', 'pmset', 'plutil', 'pgrep']:
                stub = tools / tool
                stub.write_text('#!/bin/bash\n' + {
                    'codex': 'exit "${MAC_TEST_AUTH_EXIT:-0}"\n',
                    'pgrep': 'exit "${MAC_TEST_APP_EXIT:-0}"\n',
                    'pmset': 'printf "AC Power:\\n sleep %s\\n womp 1\\n autorestart 1\\n" "${MAC_TEST_SLEEP:-0}"\n',
                }.get(tool, 'exit 0\n'))
                stub.chmod(0o755)
                source = re.sub(r'/(?:usr/)?s?bin/' + re.escape(tool) + r'\b', str(stub), source)
            script = home / 'check.sh'
            script.write_text(source)
            env = dict(os.environ, HOME=directory)
            self.assertEqual(subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True).returncode, 0)
            for overrides, error in [({'MAC_TEST_AUTH_EXIT': '1'}, 'not signed in'),
                                     ({'MAC_TEST_APP_EXIT': '1'}, 'not running'),
                                     ({'MAC_TEST_SLEEP': '1'}, 'AC power requires sleep 0')]:
                with self.subTest(overrides=overrides):
                    result = subprocess.run(['/bin/bash', str(script)], env=dict(env, **overrides), capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)
            app.rmdir()
            result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Missing desktop host', result.stderr)


if __name__ == '__main__':
    unittest.main()
