import copy
import importlib.util
from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('configure_webui', ROOT / 'files/netdata/configure_webui.py')
webui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(webui)


class NetdataIntegration(unittest.TestCase):
    def setUp(self):
        self.settings = {'openai_api_key': 'sk-test-not-a-real-key',
                         'netdata_url': 'http://192.0.2.2:19999/mcp',
                         'dashboard_url': 'http://192.0.2.2:19999',
                         'expected_nodes': ['node-a', 'node-b']}
        self.current = {'ENABLE_OPENAI_API': True,
                        'OPENAI_API_BASE_URLS': ['https://example.invalid/v1'],
                        'OPENAI_API_KEYS': ['existing-private-key'],
                        'OPENAI_API_CONFIGS': {'0': {'prefix_id': 'existing', 'api_type': 'chat_completions'}}}
        self.connections = [{'url': 'https://example.invalid/tools', 'info': {'id': 'existing'}}]

    def test_configuration_preserves_other_providers_and_tools(self):
        before = copy.deepcopy((self.current, self.connections))
        provider, tools, model = webui.desired_config(self.current, self.connections, self.settings)
        self.assertEqual((self.current, self.connections), before)
        self.assertEqual(provider['OPENAI_API_KEYS'][0], 'existing-private-key')
        self.assertEqual(provider['OPENAI_API_CONFIGS']['0'], self.current['OPENAI_API_CONFIGS']['0'])
        self.assertEqual(tools[0], self.connections[0])
        self.assertEqual(model['access_grants'], [])

    def test_reapplication_is_idempotent_and_key_stays_out_of_tools_and_prompt(self):
        first = webui.desired_config(self.current, self.connections, self.settings)
        second = webui.desired_config(first[0], first[1], self.settings)
        self.assertEqual(first, second)
        self.assertNotIn(self.settings['openai_api_key'], str(first[1:]))
        self.assertFalse(first[2]['params']['custom_params']['store'])
        self.assertEqual(first[0]['OPENAI_API_CONFIGS']['1']['api_type'], 'responses')

    def test_model_has_only_selected_observation_tools(self):
        _, tools, model = webui.desired_config(self.current, self.connections, self.settings)
        allowed = tools[-1]['config']['function_name_filter_list']
        self.assertIn('query_metrics', allowed)
        self.assertIn('list_raised_alerts', allowed)
        self.assertNotIn('execute_function', allowed)
        self.assertNotIn('list_functions', allowed)
        self.assertEqual(tools[-1]['auth_type'], 'none')
        self.assertFalse(model['meta']['capabilities']['builtin_tools'])

    def test_saved_metadata_defaults_do_not_cause_drift_but_real_changes_do(self):
        model = webui.desired_config(self.current, self.connections, self.settings)[2]
        saved = copy.deepcopy(model)
        saved['meta'].update(profile_image_url=None, knowledge=None, voice=None)
        saved['user_id'] = 'existing-admin'
        self.assertTrue(webui.model_matches(saved, model))
        saved['meta']['toolIds'].append('unexpected-tool')
        self.assertFalse(webui.model_matches(saved, model))
        self.assertFalse(webui.model_matches(None, model))

    def test_optional_observers_keep_credentials_out_of_model_and_preserve_connections(self):
        self.settings['observers'] = [{'id': 'homelab-apps', 'name': 'Linux apps',
                                      'url': 'http://192.0.2.2:19998', 'token': 'private-observer-token'}]
        first = webui.desired_config(self.current, self.connections, self.settings)
        self.assertEqual(first, webui.desired_config(first[0], first[1], self.settings))
        self.assertEqual(first[1][0], self.connections[0])
        self.assertEqual(first[1][-1]['key'], 'private-observer-token')
        self.assertNotIn('private-observer-token', str(first[2]))
        self.assertIn('server:homelab-apps', first[2]['meta']['toolIds'])
        self.assertEqual(first[1][-1]['config']['function_name_filter_list'],
                         ['list_apps', 'get_app_health', 'get_app_logs'])

    def test_netdata_templates_separate_stream_credentials_from_web_config(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'roles/netdata/templates'), undefined=StrictUndefined)
        values = {'netdata_parent': False, 'netdata_hostname': 'test-node', 'netdata_bind': '127.0.0.1',
                  'netdata_update_every': 5, 'netdata_web_clients': ['127.0.0.1'],
                  'netdata_mcp_clients': ['127.0.0.1'], 'netdata_stream_clients': [],
                  'netdata_parent_address': '192.0.2.2:19999',
                  'netdata_stream_key': '11111111-2222-3333-4444-555555555555'}
        config = env.get_template('netdata.conf.j2').render(**values)
        stream = env.get_template('stream.conf.j2').render(**values)
        self.assertIn('db = ram', config)
        self.assertIn('bind to = 127.0.0.1', config)
        self.assertIn('allow connections from = localhost 127.0.0.1', config)
        self.assertNotIn(values['netdata_stream_key'], config)
        self.assertIn('api key = ' + values['netdata_stream_key'], stream)
        values.update(netdata_parent=True, netdata_stream_clients=['192.0.2.3'])
        parent = env.get_template('netdata.conf.j2').render(**values)
        self.assertIn('dbengine tier 0 retention size = 2GiB', parent)
        self.assertIn('allow streaming from = 192.0.2.3', parent)

    def test_repair_tool_is_opt_in_and_secrets_never_enter_the_model(self):
        self.settings['repairs'] = {'source': 'private tool source', 'config': {'key': 'private repair credential'}}
        first = webui.desired_config(self.current, self.connections, self.settings)
        self.assertEqual(first, webui.desired_config(first[0], first[1], self.settings))
        model = first[2]
        self.assertIn('homelab_repairs', model['meta']['toolIds'])
        self.assertIn('action button is the approval boundary', ' '.join(model['params']['system'].split()))
        self.assertEqual(model['meta']['actionIds'], ['homelab_repair_controls'])
        self.assertNotIn('call approve_repair', model['params']['system'])
        self.assertNotIn('You cannot install, restart, repair', model['params']['system'])
        self.assertNotIn('private repair credential', str(first))
        self.assertNotIn('private tool source', str(first))
        self.assertFalse(model['meta']['capabilities']['builtin_tools'])
        del self.settings['repairs']
        readonly = webui.desired_config(first[0], first[1], self.settings)[2]['meta']
        self.assertNotIn('homelab_repairs', readonly['toolIds'])
        self.assertNotIn('actionIds', readonly)


if __name__ == '__main__':
    unittest.main()
