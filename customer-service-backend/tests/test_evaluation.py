"""Synthetic metric arithmetic tests; these are never agent benchmark results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = [
            {'id': 'one', 'category': ['single', 'explicit_id'], 'input': {'message': 'one'},
             'expected': {'intent': 'order_status', 'tool_calls': [{'name': 'query_order_status', 'args': {'order_id': 'A1'}}],
                          'success': {'checks': [{'path': 'output', 'op': 'contains', 'value': 'A1'},
                                                 {'path': 'facts.status', 'op': 'eq', 'value': 'sent'}]}}},
            {'id': 'two', 'category': ['missing_slot'], 'input': {'message': 'two'},
             'expected': {'intent': 'order_list', 'tool_calls': [],
                          'success': {'checks': [{'path': 'state.pending_intent.intent', 'op': 'eq', 'value': 'order_list'}]}}},
            {'id': 'three', 'category': ['compound'], 'input': {'message': 'three'},
             'expected': {'intent': 'multi_intent', 'success': {'checks': [{'path': 'state.tasks', 'op': 'len_eq', 'value': 2}]}}},
        ]

    def test_separate_denominators_exact_calls_and_category_coverage(self):
        records = [
            {'id': 'one', 'prediction': {'intent': 'order_status', 'tool_calls': [{'name': 'query_order_status', 'args': {'order_id': 'WRONG'}}],
             'output': 'A1 is sent', 'facts': {'status': 'sent'}}, 'capabilities': ['intent', 'tools', 'task'], 'latency_ms': 10},
            {'id': 'two', 'prediction': {'intent': 'order_status'}, 'capabilities': ['intent'], 'latency_ms': 30},
        ]
        report = evaluation.evaluate(self.scenarios, records, mode='unit-test-only')
        self.assertEqual(report['metrics']['intent_accuracy'], {'correct': 1, 'denominator': 2, 'rate': 0.5, 'unavailable': 0})
        self.assertEqual(report['metrics']['tool_call_accuracy'], {'correct': 0, 'denominator': 1, 'rate': 0.0, 'unavailable': 1})
        self.assertEqual(report['metrics']['task_success'], {'correct': 1, 'denominator': 1, 'rate': 1.0, 'unavailable': 1})
        self.assertEqual(report['coverage']['scenarios'], {'executed': 2, 'labeled': 3, 'rate': 2 / 3})
        self.assertEqual(report['coverage']['category_count'], {'executed': 3, 'labeled': 4, 'rate': 0.75})
        self.assertEqual(report['coverage']['categories']['compound']['executed'], 0)
        self.assertEqual(report['latency_ms']['mean'], 20)
        self.assertEqual(report['latency_ms']['p95'], 30)
        self.assertEqual(report['failures'][0]['failed_metrics'], ['tool_call_accuracy'])

    def test_errors_are_failures_not_dropped_from_declared_denominators(self):
        report = evaluation.evaluate(self.scenarios, [{'id': 'one', 'prediction': {}, 'error': 'boom', 'capabilities': ['intent', 'tools', 'task']}], mode='unit-test-only')
        self.assertEqual(report['errors'], [{'id': 'one', 'error': 'boom'}])
        for name in ['intent_accuracy', 'tool_call_accuracy', 'task_success']:
            metric = report['metrics'][name]
            self.assertEqual(metric['denominator'], 1)
            self.assertEqual(metric['correct'], 0)
        self.assertEqual(len(report['failures']), 1)

    def test_slot_exact_accuracy_distinguishes_wrong_id_and_invented_slots(self):
        cases = copy.deepcopy(self.scenarios[:2])
        cases[0]['expected'].update(order_id='A1', user_id=None)
        cases[1]['expected'].update(order_id=None, user_id=None)
        records = [{'id': 'one', 'prediction': {'intent': 'order_status', 'order_id': 'A2'}},
                   {'id': 'two', 'prediction': {'intent': 'order_list', 'user_id': 'invented'}}]
        report = evaluation.evaluate(cases, records, mode='unit-test-only')
        self.assertEqual(report['metrics']['intent_accuracy']['rate'], 1.0)
        self.assertEqual(report['metrics']['slot_exact_accuracy'], {'correct': 0, 'denominator': 2, 'rate': 0.0, 'unavailable': 0})

    def test_missing_inapplicable_tool_expectation_does_not_enter_denominator(self):
        report = evaluation.evaluate(self.scenarios, [{'id': 'three', 'capabilities': ['intent', 'tools', 'task'],
            'prediction': {'intent': 'multi_intent', 'tool_calls': [], 'state': {'tasks': ['a', 'b']}}}], mode='unit-test-only')
        self.assertEqual(report['metrics']['tool_call_accuracy']['denominator'], 0)
        self.assertIsNone(report['metrics']['tool_call_accuracy']['rate'])
        self.assertEqual(report['metrics']['task_success']['correct'], 1)

    def test_all_success_checks_required_missing_paths_and_type_mismatch_fail(self):
        for prediction in [{'output': 'A1', 'facts': {}}, {'output': 'A1', 'facts': {'status': 'other'}}]:
            report = evaluation.evaluate(self.scenarios, [{'id': 'one', 'capabilities': ['task'], 'prediction': prediction}], mode='unit-test-only')
            self.assertEqual(report['metrics']['task_success']['correct'], 0)
        checks = [{'path': 'count', 'op': 'eq', 'value': 1}]
        self.assertFalse(evaluation.check_success({'count': True}, checks)[0])
        self.assertFalse(evaluation.check_success({}, [{'path': 'x', 'op': 'not_contains', 'value': 'x'}])[0])

    def test_exact_call_sequence_rejects_extra_call_extra_arg_and_wrong_name(self):
        expected = [{'name': 'query_order_status', 'args': {'order_id': 'A1'}}]
        self.assertTrue(evaluation.exact_tool_calls(expected, copy.deepcopy(expected)))
        for actual in [expected + expected, [{'name': 'query_order_status', 'args': {'order_id': 'A1', 'user_id': 'u1'}}],
                       [{'name': 'query_order_logistics', 'args': {'order_id': 'A1'}}], None]:
            self.assertFalse(evaluation.exact_tool_calls(expected, actual))

    def test_success_operator_checks_are_measurable_and_strict(self):
        result = {'output': 'order A1', 'state': {'tasks': [1, 2]}, 'facts': {'writes': 0}}
        checks = [{'path': 'output', 'op': 'not_contains', 'value': 'submitted'},
                  {'path': 'state.tasks', 'op': 'len_eq', 'value': 2}, {'path': 'facts.writes', 'op': 'gte', 'value': 0}]
        self.assertTrue(evaluation.check_success(result, checks)[0])
        self.assertFalse(evaluation.check_success(result, [{'path': 'facts.writes', 'op': 'contains', 'value': 'x'}])[0])

    def test_duplicate_unknown_records_and_bad_dataset_are_rejected(self):
        for records in [[{'id': 'one'}, {'id': 'one'}], [{'id': 'absent'}]]:
            with self.assertRaises(ValueError):
                evaluation.evaluate(self.scenarios, records, mode='unit-test-only')
        invalid = copy.deepcopy(self.scenarios)
        invalid[0]['expected']['success']['checks'][0]['op'] = 'magically_true'
        with self.assertRaises(ValueError):
            evaluation.validate_dataset(invalid)
        with self.assertRaises(ValueError):
            evaluation.evaluate(self.scenarios, [], mode='')

    def test_empty_runs_are_null_and_tokens_are_observed_only(self):
        report = evaluation.evaluate(self.scenarios, [], mode='unit-test-only')
        self.assertIsNone(report['metrics']['intent_accuracy']['rate'])
        self.assertEqual(report['tokens']['records_observed'], 0)
        records = [{'id': 'one', 'prediction': {'intent': 'order_status'}, 'tokens': {'input': 11, 'output': 2, 'total': 13}},
                   {'id': 'two', 'prediction': {'intent': 'order_list'}}]
        report = evaluation.evaluate(self.scenarios, records, mode='unit-test-only')
        self.assertEqual(report['tokens'], {'records_observed': 1, 'records_missing': 1, 'input': 11, 'output': 2, 'total': 13})

    def test_runner_never_exposes_labels_to_adapter_and_saves_actual_failures(self):
        import evaluate_agent
        received = []
        def adapter(payload):
            received.append(payload)
            return {'intent': 'wrong', 'capabilities': ['intent'], 'tokens': {'total': 5}}
        records = evaluate_agent.run_scenarios(self.scenarios[:1], adapter, capabilities=None)
        self.assertEqual(received, [{'message': 'one', 'scenario_id': 'one'}])
        self.assertNotIn('expected', received[0])
        report = evaluation.evaluate(self.scenarios, records, mode='synthetic-unit-test')
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / 'result'
            evaluate_agent.write_reports(prefix, report, records)
            saved = json.loads(prefix.with_suffix('.json').read_text())
            self.assertEqual(saved['report']['metrics']['intent_accuracy']['correct'], 0)
            self.assertIn('synthetic-unit-test', prefix.with_suffix('.md').read_text())
            self.assertEqual(saved['records'][0]['tokens']['total'], 5)

    def test_runner_catches_adapter_errors_continues_and_supports_async(self):
        import evaluate_agent
        async def adapter(payload):
            if payload['scenario_id'] == 'one':
                raise RuntimeError('isolated failure')
            return {'intent': 'order_list'}
        records = evaluate_agent.run_scenarios(self.scenarios[:2], adapter, capabilities=['intent', 'task'])
        self.assertEqual('RuntimeError', records[0]['error'])
        self.assertNotIn('isolated failure', records[0]['error'])
        self.assertEqual(records[1]['prediction']['intent'], 'order_list')
        self.assertEqual(records[0]['capabilities'], ['intent', 'task'])
        self.assertGreaterEqual(records[0]['latency_ms'], 0)


if __name__ == '__main__':
    unittest.main()
