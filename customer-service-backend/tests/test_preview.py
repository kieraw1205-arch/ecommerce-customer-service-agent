"""Preview configuration and offline demonstration are not live model benchmarks."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class PreviewTests(unittest.TestCase):
    def test_model_configuration_never_autoloads_dotenv(self):
        loader = Mock()
        import my_agent.llm as module
        with patch.dict(sys.modules, {'dotenv': SimpleNamespace(load_dotenv=loader)}):
            importlib.reload(module)
        loader.assert_not_called()
        self.assertEqual(module.llm.model_name, os.environ['LLM_MODEL'])

    def test_offline_example_executes_graph_sse_and_keeps_identity_private(self):
        root = Path(__file__).resolve().parents[1]
        script = root/'examples'/'offline_demo.py'
        self.assertTrue(script.is_file(), 'offline example is not implemented')
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence['mode'], 'offline-model-and-http-fixtures')
        self.assertEqual(evidence['live_model_calls'], 0)
        self.assertEqual(evidence['business_writes'], 0)
        self.assertTrue(evidence['history_restored'])
        self.assertTrue(evidence['other_user_history_empty'])
        self.assertEqual(len(evidence['turns']), 3)
        self.assertIn('待发货', evidence['turns'][1]['reply'])
        self.assertIn('FIXTURE-TRACK-1', evidence['turns'][2]['reply'])
        self.assertTrue(all('done' in t['events'] and 'node' in t['events'] for t in evidence['turns']))
        self.assertFalse(any(t['tokens']['reported'] for t in evidence['turns']))
        self.assertNotIn('Bearer ', result.stdout)
        self.assertNotIn('Authorization', result.stdout)
