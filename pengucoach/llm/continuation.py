"""Recoverable output limits, immutable request snapshots and visible append rules."""
import copy
import json


def public(value):
    return {k: v for k, v in value.items() if not k.startswith('_')}


def json_value(value):
    return json.loads(json.dumps(value, default=str))


def append_text(previous, addition):
    if not previous:
        return addition
    # Remove only exact repeated overlap; never summarize or replace the old text.
    for length in range(min(len(previous), len(addition), 12000), 15, -1):
        if previous[-length:] == addition[:length]:
            return previous + addition[length:]
    return previous + '\n\n' + addition if addition else previous


def total_usage(first, second):
    result = {}
    for key in {'input_tokens', 'output_tokens', 'total_tokens'} | set(first) | set(second):
        a, b = first.get(key), second.get(key)
        result[key] = a+b if isinstance(a, int) and isinstance(b, int) else None
    return result


def merge_metadata(old, answer):
    old, answer = copy.deepcopy(old), copy.deepcopy(answer)
    costs = old.get('cost_eur'), answer.get('cost_eur')
    old.update({k: answer[k] for k in ('stop_reason', 'truncated', 'empty_due_to_limit', 'context_window_tokens',
        'max_output_tokens', 'output_budget_adjusted', 'messages_truncated', '_resume') if k in answer})
    old['usage_complete'] = old.get('usage_complete', True) and answer.get('usage_complete', True)
    old['usage'] = total_usage(old.get('usage') or {}, answer.get('usage') or {})
    old['cost_eur'] = round(sum(costs), 8) if all(isinstance(c, (int, float)) for c in costs) else None
    old['elapsed_seconds'] = (old.get('elapsed_seconds') or 0)+(answer.get('elapsed_seconds') or 0)
    output = old['usage'].get('output_tokens')
    old['tokens_per_second'] = round(output/old['elapsed_seconds'], 3) if isinstance(output, int) and old['elapsed_seconds'] > 0 else None
    old['continuation_calls'] = [*(old.get('continuation_calls') or []),
        {'usage': answer.get('usage'), 'cost_eur': answer.get('cost_eur'), 'stop_reason': answer.get('stop_reason'),
         'max_output_tokens': answer.get('max_output_tokens')}]
    if not answer.get('truncated'):
        old.pop('_resume', None)
    return old
