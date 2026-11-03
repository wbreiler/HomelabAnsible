"""Token-based USD estimates for the models used by homelab workers."""
import re

# Standard API prices per million tokens, verified 2026-11-03.
# https://developers.openai.com/api/docs/pricing
# https://developers.openai.com/api/docs/guides/prompt-caching#monitor-cache-performance
RATES = {'gpt-4.1-mini': (0.40, 0.10, 1.60),
         'gpt-6.1-sol': (2.00, 0.10, 10.00), 'gpt-6-astra': (10.00, 1.00, 50.00)}


def record(response=None, requested_model=None):
    result = {'attempted': requested_model is not None, 'model': requested_model,
              'confirmed': False, 'cost_usd': None if requested_model else 0}
    if not response:
        return result
    model = response.get('model', '')
    result.update(model=model if re.fullmatch(r'[A-Za-z0-9._-]{1,100}', model) else requested_model,
                  confirmed=bool(model), service_tier=response.get('service_tier'))
    usage = response.get('usage') or {}
    result['usage'] = usage
    base = next((name for name in RATES if model == name or re.fullmatch(re.escape(name) + r'-\d{4}-\d{2}-\d{2}', model)), None)
    # shortcut: only standard, text-only calls are priced; add rates before changing tier/model.
    if not base or result['service_tier'] != 'default':
        return result
    try:
        total, output = usage['input_tokens'], usage['output_tokens']
        details = usage['input_tokens_details']
        cached, written = details['cached_tokens'], details.get('cache_write_tokens', 0)
        writes = details.get('cache_write_tokens_details', {})
        short, long = writes.get('ttl_30m_tokens', 0), writes.get('ttl_12h_tokens', 0)
        counts = [total, output, cached, written, short, long]
        if any(type(value) is not int or value < 0 for value in counts) or cached + written > total or short + long != written:
            return result
        if written and base == 'gpt-4.1-mini':
            return result
        input_rate, cached_rate, output_rate = RATES[base]
        if total > 272000 and base != 'gpt-4.1-mini':
            input_rate, cached_rate, output_rate = input_rate * 2, cached_rate * 2, output_rate * 1.5
        # output_tokens already includes reasoning tokens.
        result['cost_usd'] = ((total-cached-written + short*1.25 + long*2.5)*input_rate +
                              cached*cached_rate + output*output_rate) / 1_000_000
    except (KeyError, TypeError, ValueError):
        pass
    return result


def label(usage):
    if usage is None:
        return 'AI cost unavailable (usage not recorded)'
    if not usage['attempted']:
        return 'AI: none · $0 (no API call)'
    model = usage.get('model') or 'unknown model'
    if not usage.get('confirmed'):
        model += ' (requested)'
    cost = usage.get('cost_usd')
    return model + (' · cost unavailable' if cost is None else f' · ~${cost:.6f} USD')
