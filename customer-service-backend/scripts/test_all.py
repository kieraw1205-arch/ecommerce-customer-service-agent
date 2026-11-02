"""Run every E3/E4 test with a fresh SQLite checkpoint and blocked live I/O."""
from pathlib import Path
import sys
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'evaluation'))

def main():
    os.environ['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'evaluation')])
    # Offline verification never inherits a live provider or business endpoint.
    os.environ.update(LLM_MODEL='offline-fixture', LLM_API_KEY='offline-not-a-secret',
        LLM_BASE_URL='http://127.0.0.1:1/v1', LLM_MAX_RETRIES='0', LLM_TIMEOUT='1',
        ECOMMERCE_API_BASE_URL='http://127.0.0.1:1', AGENT_CHECKPOINT_BACKEND='sqlite')
    import my_agent.checkpoint as checkpoint
    with tempfile.TemporaryDirectory(prefix='ecommerce-agent-tests-') as tmp:
        checkpoint.DB_PATH=Path(tmp)/'checkpoints.sqlite'
        from my_agent import nodes
        with patch('httpx.get',side_effect=httpx.ConnectError('live network blocked by test runner')), \
             patch('httpx.post',side_effect=AssertionError('live business writes blocked by test runner')), \
             patch.object(nodes,'llm_with_tools') as model:
            model.invoke.side_effect=TimeoutError('live Qwen blocked by test runner')
            suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1

if __name__=='__main__': raise SystemExit(main())
