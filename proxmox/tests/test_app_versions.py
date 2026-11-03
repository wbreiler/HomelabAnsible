"""Read-only release comparisons for custom apps, source builds, and images."""
import importlib.util
import json
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('versions', Path(__file__).resolve().parents[1] / 'roles/maintenance_queries/files/app_versions.py')
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
DIGEST = 'sha256:' + 'a'*64
OTHER = 'sha256:' + 'b'*64
CONFIG = 'sha256:' + 'c'*64


def image(**values):
    return {'ref': 'ghcr.io/example/app:1.0.0@'+DIGEST, 'image_id': CONFIG, 'app': 'example', 'service': 'web',
            'os': 'linux', 'arch': 'amd64', 'variant': '', 'digests': ['ghcr.io/example/app@'+DIGEST], **values}


class Versions(unittest.TestCase):
    def test_channel_is_preserved_but_numeric_pin_checks_latest(self):
        self.assertEqual(v.image_target(image()), 'ghcr.io/example/app:latest')
        self.assertEqual(v.image_target(image(ref='nginx:stable-alpine@'+DIGEST)), 'nginx:stable-alpine')
        self.assertEqual(v.image_target(image(ref='registry.example:5000/app:v2')), 'registry.example:5000/app:latest')
        for ref in ['--help', 'repo; rm -rf /', 'https://user:secret@evil.test/image']:
            with self.assertRaises(ValueError):
                v.image_target(image(ref=ref))

    def test_multiarch_index_change_is_not_a_false_update(self):
        manifest = {'digest': OTHER, 'manifests': [
            {'digest': OTHER, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
            {'digest': DIGEST, 'platform': {'os': 'linux', 'architecture': 'amd64'},
             'annotations': {'org.opencontainers.image.version': '1.0.0'}}]}
        calls = []
        def run(args):
            calls.append(args)
            return json.dumps(manifest)
        row = v.image_update(image(), run)
        self.assertIsNone(row['available'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(call[:4] == ['docker','buildx','imagetools','inspect'] for call in calls))

    def test_config_digest_prevents_false_positive_after_index_repack(self):
        replies = [{'digest': OTHER, 'annotations': {'org.opencontainers.image.version': '1.0.0'}}, {'config': {'digest': CONFIG}}]
        with patch.object(v, 'command', side_effect=lambda args: json.dumps(replies.pop(0))) as run:
            row = v.image_update(image(), run)
        self.assertIsNone(row['available'])

    def test_image_update_names_release_and_never_pulls(self):
        replies = [{'digest': OTHER, 'annotations': {'org.opencontainers.image.version': '2.0.0'}}, {'config': {'digest': OTHER}}]
        with patch.object(v, 'command', side_effect=lambda args: json.dumps(replies.pop(0))) as run:
            row = v.image_update(image(), run)
        self.assertEqual(row['available'], '2.0.0')
        self.assertTrue(all(call.args[0][:4] == ['docker','buildx','imagetools','inspect'] for call in run.call_args_list))

    def test_local_build_compares_source_without_looking_up_local_image_in_registry(self):
        local = image(ref='cobalt-web:abcdef0-custom', digests=[], app='cobalt', source='', revision='')
        with patch.object(v, 'public_json', side_effect=[{'tag_name': 'v2.0.0'}, {'ahead_by': 2}]), patch.object(v, 'command') as run:
            row = v.image_update(local, run)
        self.assertEqual(row['available'], 'v2.0.0')
        self.assertTrue(row['manual'])
        run.assert_not_called()

    def test_source_without_releases_compares_default_branch(self):
        local = image(ref='cobalt-web:abcdef0-custom', digests=[], app='cobalt', source='', revision='')
        responses = [urllib.error.HTTPError('https://api.github.com', 404, 'Not Found', {}, None),
                     {'default_branch':'main'}, {'sha':'d'*40}, {'ahead_by':0}]
        with patch.object(v,'public_json',side_effect=responses):
            row=v.image_update(local)
        self.assertEqual(row['latest'],'main '+('d'*12))
        self.assertIsNone(row['available'])
        self.assertNotIn('unavailable',row)

    def test_same_version_new_image_is_labeled_rebuild(self):
        responses=[{'digest':OTHER,'annotations':{'org.opencontainers.image.version':'1.0.0'}},
                   {'config':{'digest':OTHER}}]
        with patch.object(v,'command',side_effect=lambda args:json.dumps(responses.pop(0))) as run:
            row=v.image_update(image(),run)
        self.assertEqual(row['available'],'1.0.0 (image rebuild)')

    def test_base_image_os_label_does_not_replace_app_version(self):
        manifest={'digest':DIGEST,'annotations':{'org.opencontainers.image.version':'1.0.0'}}
        row=v.image_update(image(version='24.04'),lambda args:json.dumps(manifest))
        self.assertEqual(row['current'],'1.0.0')

    def test_hub_uses_platform_metadata_and_most_specific_version_alias(self):
        latest={'digest':OTHER,'name':'latest','images':[{'digest':OTHER,'os':'linux','architecture':'amd64'}]}
        tags=[{**latest,'name':'2.0'},{**latest,'name':'2.0.2'},
              {'digest':DIGEST,'name':'1.0.0','images':[{'digest':DIGEST,'os':'linux','architecture':'amd64'}]}]
        with patch.object(v,'public_json',side_effect=[latest,{'results':tags}]), patch.object(v,'command') as run:
            row=v.image_update(image(ref='example/app:1.0.0@'+DIGEST),run)
        self.assertEqual(row['available'],'2.0.2')
        run.assert_not_called()

    def test_hub_index_change_on_another_platform_is_not_an_update(self):
        latest={'digest':OTHER,'images':[{'digest':DIGEST,'os':'linux','architecture':'amd64'}]}
        with patch.object(v,'public_json',side_effect=[latest,{'results':[]}]), patch.object(v,'command') as run:
            row=v.image_update(image(ref='example/app:1.0.0@'+DIGEST),run)
        self.assertIsNone(row['available'])
        run.assert_not_called()

    def test_hub_missing_old_index_metadata_is_explicit(self):
        latest={'digest':OTHER,'images':[{'digest':OTHER,'os':'linux','architecture':'amd64'}]}
        with patch.object(v,'public_json',side_effect=[latest,{'results':[]}]):
            row=v.image_update(image(ref='example/app:1.0.0@'+DIGEST))
        self.assertTrue(row['comparison_uncertain'])
        self.assertIn('platform needs review',row['available'])

    def test_netboot_checks_payload_digest_not_secure_boot_shim(self):
        release = {'tag_name': '2.0.90', 'published_at': '2026-01-01', 'assets': [{'name':'netboot.xyz.efi','digest':DIGEST}]}
        latest = {'tag_name': '2.0.91', 'published_at': '2026-02-01', 'assets': [{'name':'netboot.xyz.efi','digest':None}]}
        with patch.object(v, 'public_json', return_value=[latest, release]):
            row = v.native_upstream({'app':'netboot_xyz','hashes':{'netboot.xyz-unsigned.efi':DIGEST[7:]}})
        self.assertEqual(row['current'], '2.0.90')
        self.assertEqual(row['available'], '2.0.91')

    def test_modrinth_respects_game_loader_and_release_type(self):
        installed = {'project_id':'project','version_number':'1.0','date_published':'2026-01-01'}
        releases = [{'version_number':'2.0','version_type':'beta','date_published':'2026-03-01'},
                    {'version_number':'1.1','version_type':'release','date_published':'2026-02-01'}]
        pack={'current_id':'version','MC_VERSION':'1.21.1','LOADER':'fabric','PACK_NAME':'Pack','vmid':100}
        with patch.object(v, 'public_json', side_effect=[installed,releases]) as request:
            row=v.modrinth(pack)
        self.assertEqual(row['available'],'1.1')
        self.assertIn('game_versions=',request.call_args.args[0])
        self.assertIn('loaders=',request.call_args.args[0])

    def test_curseforge_key_stays_in_guest_request_header_and_latest_stable_wins(self):
        installed={'displayName':'Pack 1','fileDate':'2026-01-01','isServerPack':False}
        releases=[{'displayName':'Pack 2','fileDate':'2026-02-01','isServerPack':False,'releaseType':1},
                  {'displayName':'Pack 3 beta','fileDate':'2026-03-01','isServerPack':False,'releaseType':2}]
        pack={'PACK_NAME':'Pack','PACK_SOURCE':'manual','vmid':100,'current_id':'123','CURSEFORGE_PROJECT_ID':'456','MC_VERSION':'1.21.1'}
        with patch.object(v,'pack_config',return_value={'CURSEFORGE_API_KEY':'private-secret'}), \
                patch.object(v,'fetch',side_effect=[{'data':installed},{'data':releases}]) as request:
            rows=v.curseforge([pack])
        self.assertEqual(rows[0]['available'],'Pack 2')
        self.assertNotIn('private-secret',json.dumps(rows))
        self.assertNotIn('private-secret',request.call_args.args[0])
        self.assertEqual(request.call_args.args[1],{'x-api-key':'private-secret'})


if __name__ == '__main__':
    unittest.main()
