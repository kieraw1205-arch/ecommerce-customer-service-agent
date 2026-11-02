"""Dependency-free, evidence-based metrics for an independently labeled dataset.

An executed record is not necessarily observed for every metric: capabilities
must distinguish intent-only from end-to-end runs. Errors remain incorrect in
all applicable, supported denominators. Missing capability earns no credit.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math
from statistics import mean

SLOTS = ('user_id', 'order_id', 'product_id', 'refund_reason', 'sub_intents')
OPERATORS = {'eq', 'contains', 'not_contains', 'gte', 'len_eq'}
CAPABILITIES = {'intent', 'slots', 'tools', 'task'}
MISSING = object()


def strict_equal(left, right):
    """JSON equality without Python's True == 1 or object-key ordering issues."""
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def validate_dataset(scenarios):
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError('Dataset must be a nonempty JSON list')
    ids = set()
    for case in scenarios:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'] or case['id'] in ids:
            raise ValueError('Each scenario requires a unique nonempty string id')
        ids.add(case['id'])
        if not isinstance(case.get('category'), list) or not case['category'] or any(not isinstance(tag, str) or not tag for tag in case['category']):
            raise ValueError(f"{case['id']}: category must contain nonempty tags")
        if not isinstance(case.get('input'), dict) or not isinstance(case['input'].get('message'), str):
            raise ValueError(f"{case['id']}: input.message must be a string")
        expected = case.get('expected')
        if not isinstance(expected, dict) or not isinstance(expected.get('intent'), str):
            raise ValueError(f"{case['id']}: expected.intent is required")
        if 'tool_calls' in expected and not valid_calls(expected['tool_calls']):
            raise ValueError(f"{case['id']}: tool_calls must be an exact list of name/args objects")
        success = expected.get('success', {})
        if not isinstance(success, dict):
            raise ValueError(f"{case['id']}: invalid success oracle")
        checks = success.get('checks', [])
        if not isinstance(checks, list):
            raise ValueError(f"{case['id']}: checks must be a list")
        for check in checks:
            if not isinstance(check, dict) or check.get('op') not in OPERATORS or not isinstance(check.get('path'), str) or not check['path'] or 'value' not in check:
                raise ValueError(f"{case['id']}: invalid measurable check")
    return scenarios


def valid_calls(calls):
    return isinstance(calls, list) and all(isinstance(call, dict) and set(call) == {'name', 'args'}
        and isinstance(call['name'], str) and isinstance(call['args'], dict) for call in calls)


def exact_tool_calls(expected, actual):
    """Compare the whole sequence. Strip framework call IDs in the adapter."""
    return valid_calls(actual) and strict_equal(expected, actual)


def get_path(record, path):
    value = record
    for key in path.split('.'):
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return MISSING
    return value


def check_success(prediction, checks):
    details = []
    for check in checks:
        actual = get_path(prediction, check['path'])
        expected, op = check['value'], check['op']
        passed = False
        if actual is not MISSING:
            try:
                if op == 'eq':
                    passed = strict_equal(actual, expected)
                elif op in {'contains', 'not_contains'}:
                    if isinstance(actual, str) and isinstance(expected, str):
                        passed = expected in actual
                    elif isinstance(actual, (list, dict)):
                        passed = expected in actual
                    else:
                        raise TypeError('not a supported container')
                    if op == 'not_contains':
                        passed = not passed
                elif op == 'gte':
                    passed = type(actual) in {int, float} and type(expected) in {int, float} and actual >= expected
                elif op == 'len_eq':
                    passed = isinstance(actual, (str, list, dict)) and type(expected) is int and len(actual) == expected
            except (TypeError, ValueError):
                passed = False
        details.append({**check, 'passed': bool(passed), 'actual': None if actual is MISSING else actual, 'missing': actual is MISSING})
    return bool(checks) and all(item['passed'] for item in details), details


def infer_capabilities(prediction):
    capabilities = set(prediction.get('capabilities', []))
    if not capabilities:
        if 'intent' in prediction:
            capabilities.add('intent')
        if 'tool_calls' in prediction:
            capabilities.add('tools')
        if any(key in prediction for key in ('output', 'facts', 'state')):
            capabilities.add('task')
    if 'intent' in capabilities:
        capabilities.add('slots')
    return capabilities


def _metric(correct, denominator, unavailable):
    return {'correct': correct, 'denominator': denominator, 'rate': correct / denominator if denominator else None, 'unavailable': unavailable}


def evaluate(scenarios, records, *, mode):
    validate_dataset(scenarios)
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError('A nonempty mode provenance label is required')
    by_id = {case['id']: case for case in scenarios}
    seen = set()
    counters = {name: Counter() for name in ('intent_accuracy', 'slot_exact_accuracy', 'tool_call_accuracy', 'task_success')}
    failures, errors, observations = [], [], []
    for record in records:
        case_id = record.get('id')
        if case_id not in by_id or case_id in seen:
            raise ValueError(f'Unknown or duplicate record id: {case_id}')
        seen.add(case_id)
        expected = by_id[case_id]['expected']
        prediction = record.get('prediction') or {}
        if not isinstance(prediction, dict):
            raise ValueError('record.prediction must be a dict')
        capabilities = set(record.get('capabilities', infer_capabilities(prediction)))
        if capabilities - CAPABILITIES:
            raise ValueError('Unknown adapter capability')
        if 'intent' in capabilities:
            capabilities.add('slots')
        error = record.get('error') or prediction.get('error')
        if error:
            errors.append({'id': case_id, 'error': str(error)})
        checks = expected.get('success', {}).get('checks', [])
        labeled_slots = {key: expected[key] for key in SLOTS if key in expected}
        task_pass, check_details = check_success(prediction, checks)
        specs = [
            ('intent_accuracy', True, 'intent', prediction.get('intent') == expected['intent']),
            ('slot_exact_accuracy', bool(labeled_slots), 'slots', all(strict_equal(prediction.get(key), value) for key, value in labeled_slots.items())),
            ('tool_call_accuracy', 'tool_calls' in expected, 'tools', exact_tool_calls(expected.get('tool_calls', []), prediction.get('tool_calls'))),
            ('task_success', bool(checks), 'task', task_pass),
        ]
        failed, unavailable = [], []
        for name, applicable, capability, passed in specs:
            if not applicable:
                continue
            if capability not in capabilities:
                counters[name]['unavailable'] += 1
                unavailable.append(name)
                continue
            counters[name]['denominator'] += 1
            if passed and not error:
                counters[name]['correct'] += 1
            else:
                failed.append(name)
        observation = {'id': case_id, 'failed_metrics': failed, 'unavailable_metrics': unavailable, 'checks': check_details}
        observations.append(observation)
        if failed or error:
            failures.append({**observation, 'expected': expected, 'prediction': prediction, 'error': str(error) if error else None})
    labeled_tags = Counter(tag for case in scenarios for tag in set(case['category']))
    executed_tags = Counter(tag for case in scenarios if case['id'] in seen for tag in set(case['category']))
    categories = {tag: {'executed': executed_tags[tag], 'labeled': total, 'rate': executed_tags[tag] / total} for tag, total in sorted(labeled_tags.items())}
    latency = [r['latency_ms'] for r in records if type(r.get('latency_ms')) in {float, int} and math.isfinite(r['latency_ms']) and r['latency_ms'] >= 0]
    latency.sort()
    token_records = [r['tokens'] for r in records if isinstance(r.get('tokens'), dict) and any(type(v) is int and v >= 0 for v in r['tokens'].values())]
    tokens = {'records_observed': len(token_records), 'records_missing': len(records) - len(token_records)}
    for field in ('input', 'output', 'total'):
        observed = [item[field] for item in token_records if type(item.get(field)) is int and item[field] >= 0]
        tokens[field] = sum(observed) if observed else None
    return {
        'schema_version': 1, 'mode': mode, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'metrics': {name: _metric(count['correct'], count['denominator'], count['unavailable']) for name, count in counters.items()},
        'coverage': {'scenarios': {'executed': len(seen), 'labeled': len(scenarios), 'rate': len(seen) / len(scenarios)},
            'category_count': {'executed': len(executed_tags), 'labeled': len(labeled_tags), 'rate': len(executed_tags) / len(labeled_tags)}, 'categories': categories},
        'latency_ms': {'records_observed': len(latency), 'mean': mean(latency) if latency else None,
            'p50': latency[math.ceil(len(latency) * .5) - 1] if latency else None,
            'p95': latency[math.ceil(len(latency) * .95) - 1] if latency else None},
        'tokens': tokens, 'errors': errors, 'failures': failures, 'observations': observations,
    }
