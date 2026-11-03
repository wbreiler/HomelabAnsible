"""Check cost arithmetic against published standard token prices."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('openai_usage', Path(__file__).resolve().parents[1] / 'files/openai_usage.py')
ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai)


def response(model='gpt-4.1-mini-2025-04-14', **usage):
    return {'model': model, 'service_tier': 'default', 'usage': {
        'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 400},
        'output_tokens': 100, 'output_tokens_details': {'reasoning_tokens': 60}, **usage}}


class Usage(unittest.TestCase):
    def test_cached_input_and_reasoning_are_not_double_counted(self):
        info = ai.record(response(), 'gpt-4.1-mini')
        self.assertAlmostEqual(info['cost_usd'], 0.00044)
        self.assertIn('gpt-4.1-mini-2025-04-14 · ~$0.000440 USD', ai.label(info))

    def test_both_cache_write_lifetimes_and_repair_models(self):
        usage = {'input_tokens': 12000, 'input_tokens_details': {'cached_tokens': 4000, 'cache_write_tokens': 7000,
                 'cache_write_tokens_details': {'ttl_30m_tokens': 3000, 'ttl_12h_tokens': 4000}}}
        for model, expected in [('gpt-6.1-sol', 0.0309), ('gpt-6-astra', 0.1565)]:
            self.assertAlmostEqual(ai.record(response(model, **usage), model)['cost_usd'], expected)

    def test_long_context_rates(self):
        info = ai.record(response('gpt-6.1-sol', input_tokens=300000), 'gpt-6.1-sol')
        self.assertAlmostEqual(info['cost_usd'], ((299600*4)+(400*0.2)+(100*15))/1e6)

    def test_unknown_model_tier_or_usage_does_not_invent_a_cost(self):
        for value in [response('unknown'), {**response(), 'service_tier': 'priority'},
                      {**response(), 'usage': None}, response(input_tokens=-1),
                      response(input_tokens_details={'cached_tokens': 1001}),
                      response('gpt-6.1-sol', input_tokens_details={'cached_tokens': 0, 'cache_write_tokens': 100})]:
            self.assertIsNone(ai.record(value, 'gpt-4.1-mini')['cost_usd'])

    def test_no_call_failure_and_historical_usage_are_distinct(self):
        self.assertEqual(ai.label(ai.record()), 'AI: none · $0 (no API call)')
        self.assertIn('(requested) · cost unavailable', ai.label(ai.record(requested_model='gpt-6.1-sol')))
        self.assertIn('usage not recorded', ai.label(None))


if __name__ == '__main__':
    unittest.main()
