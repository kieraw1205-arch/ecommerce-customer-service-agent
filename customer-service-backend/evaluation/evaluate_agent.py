#!/usr/bin/env python3
"""Run a separately supplied adapter; this CLI never supplies expected labels."""
import argparse
import asyncio
import copy
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import time

from evaluation import evaluate, infer_capabilities, validate_dataset


def run_scenarios(scenarios, adapter, *, capabilities=None):
    records = []
    for scenario in scenarios:
        payload = copy.deepcopy(scenario['input'])
        payload['scenario_id'] = scenario['id']
        started = time.perf_counter()
        record = {'id': scenario['id'], 'prediction': {}}
        if capabilities is not None:
            record['capabilities'] = list(capabilities)
        try:
            result = adapter(payload)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            if not isinstance(result, dict):
                raise TypeError('Adapter must return a dict')
            # Require JSON-serializable evidence; do not silently stringify states.
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            record['prediction'] = result
            record.setdefault('capabilities', sorted(infer_capabilities(result)))
            if result.get('error'):
                record['error'] = str(result['error'])
            if isinstance(result.get('tokens'), dict):
                record['tokens'] = result['tokens']
            if type(result.get('latency_ms')) in {int, float}:
                record['adapter_latency_ms'] = result['latency_ms']
        except Exception as exc:
            record['error'] = type(exc).__name__
            record.setdefault('capabilities', [])
        record['latency_ms'] = (time.perf_counter() - started) * 1000
        records.append(record)
    return records


def markdown_report(report):
    lines = [f"# Agent evaluation — {report['mode']}", '',
        f"Generated: {report['generated_at']}", '',
        'Observed records only. A missing capability is unavailable, never a successful task.', '',
        '| Metric | Correct | Denominator | Rate | Unavailable |', '|---|---:|---:|---:|---:|']
    for name, metric in report['metrics'].items():
        rate = f"{metric['rate']:.2%}" if metric['rate'] is not None else 'N/A'
        lines.append(f"| {name} | {metric['correct']} | {metric['denominator']} | {rate} | {metric['unavailable']} |")
    coverage = report['coverage']
    lines += ['', f"Scenarios executed/labeled: {coverage['scenarios']['executed']}/{coverage['scenarios']['labeled']}",
        f"Category tags executed/labeled: {coverage['category_count']['executed']}/{coverage['category_count']['labeled']}", '',
        '| Category | Executed | Labeled |', '|---|---:|---:|']
    for category, values in coverage['categories'].items():
        lines.append(f"| {category} | {values['executed']} | {values['labeled']} |")
    lines += ['', '## Observability', '', f"Latency (ms): `{json.dumps(report['latency_ms'])}`", '',
        f"Tokens (observed only): `{json.dumps(report['tokens'])}`", '', f"Runtime errors: {len(report['errors'])}", '', '## Failures', '']
    if not report['failures']:
        lines.append('No observed failures. Inspect denominators and unavailable metrics before drawing conclusions.')
    for failure in report['failures']:
        lines.append(f"- {failure['id']}: {', '.join(failure['failed_metrics']) or 'runtime error'}")
        if failure['error']:
            lines.append(f"  - Error: {failure['error']}")
        for check in failure['checks']:
            if not check['passed']:
                lines.append(f"  - `{check['path']}` {check['op']} `{json.dumps(check['value'], ensure_ascii=False)}`; actual `{json.dumps(check['actual'], ensure_ascii=False)}`, missing={check['missing']}")
    return '\n'.join(lines) + '\n'


def write_reports(prefix, report, records):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix('.json').write_text(json.dumps({'report': report, 'records': records}, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    prefix.with_suffix('.md').write_text(markdown_report(report), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).with_name('scenarios.json'))
    parser.add_argument('--adapter', required=True, help='Importable module:function; adapter must be safe for the chosen environment')
    parser.add_argument('--mode', required=True, help='Provenance label, e.g. live-intent or isolated-e2e')
    parser.add_argument('--output-prefix', type=Path, required=True)
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--capabilities', nargs='+', choices=['intent', 'slots', 'tools', 'task'], help='Declare before execution so adapter errors remain in the appropriate denominators')
    args = parser.parse_args(argv)
    scenarios = validate_dataset(json.loads(args.dataset.read_text(encoding='utf-8')))
    selected = scenarios
    if args.ids:
        unknown = set(args.ids) - {case['id'] for case in scenarios}
        if unknown:
            parser.error(f'Unknown IDs: {sorted(unknown)}')
        selected = [case for case in selected if case['id'] in args.ids]
    if args.limit is not None:
        if args.limit < 1:
            parser.error('--limit must be positive')
        selected = selected[:args.limit]
    module, separator, function = args.adapter.partition(':')
    if not separator or not function:
        parser.error('--adapter must be module:function')
    adapter = getattr(importlib.import_module(module), function)
    if not callable(adapter):
        parser.error('adapter is not callable')
    records = run_scenarios(selected, adapter, capabilities=args.capabilities)
    report = evaluate(scenarios, records, mode=args.mode)
    report['provenance'] = {'adapter': args.adapter, 'dataset': str(args.dataset.resolve()),
        'dataset_sha256': hashlib.sha256(args.dataset.read_bytes()).hexdigest(), 'selected_ids': [case['id'] for case in selected],
        'declared_capabilities': args.capabilities}
    write_reports(args.output_prefix, report, records)
    print(json.dumps({'mode': args.mode, 'metrics': report['metrics'], 'executed': len(records), 'errors': len(report['errors'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
