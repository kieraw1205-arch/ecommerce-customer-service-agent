"""Run the real Agent/SSE application with explicit offline boundary fixtures.

No provider call, real business API, MySQL, or business write is performed.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # Override any inherited live configuration. Never discover or read .env.
    os.environ.update(LLM_MODEL='offline-fixture', LLM_API_KEY='offline-not-a-secret',
        LLM_BASE_URL='http://127.0.0.1:1/v1', LLM_MAX_RETRIES='0', LLM_TIMEOUT='1',
        ECOMMERCE_API_BASE_URL='http://offline.invalid', AGENT_CHECKPOINT_BACKEND='sqlite')
    alice, bob = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    os.environ['AGENT_AUTH_TOKENS_JSON'] = json.dumps({alice:'example_alice',bob:'example_bob'})
    with tempfile.TemporaryDirectory(prefix='agent-core-demo-') as directory:
        import my_agent.checkpoint as cp
        cp.DB_PATH = Path(directory)/'checkpoint.sqlite'
        from fastapi.testclient import TestClient
        from langchain_core.messages import AIMessage
        import httpx
        from my_agent import nodes
        from my_agent.app import app
        from my_agent.intent import IntentResult
        from my_agent.runtime import thread_config

        def intent(user_message, history=None):
            text = user_message
            kind = 'logistics' if '物流' in text else 'order_status'
            return IntentResult(intent=kind, order_id='DEMO_ORDER_1' if 'DEMO_ORDER_1' in text else None,
                                reason='Explicit offline fixture, not a model prediction')

        def get(url, **options):
            if options.get('headers',{}).get('Authorization') != 'Bearer '+alice:
                return httpx.Response(403,request=httpx.Request('GET',url))
            if url.endswith('/orders/DEMO_ORDER_1/status'):
                data={'order_id':'DEMO_ORDER_1','status':'待发货','status_desc':'虚构离线订单正在备货'}
            elif url.endswith('/orders/DEMO_ORDER_1/logistics'):
                data={'order_id':'DEMO_ORDER_1','status':'运输中','status_desc':'离线轨迹示例',
                      'logistics_company':'虚构物流','tracking_number':'FIXTURE-TRACK-1',
                      'traces':[{'time':'2026-01-01T12:00:00','desc':'虚构分拣中心'}]}
            else:
                return httpx.Response(404,request=httpx.Request('GET',url))
            return httpx.Response(200,json={'code':0,'data':data},request=httpx.Request('GET',url))

        conversation=str(uuid4()); turns=[]
        with patch.object(nodes,'recognize_intent',side_effect=intent), \
             patch.object(nodes,'llm_with_tools') as model, \
             patch('httpx.get',side_effect=get), \
             patch('httpx.post',side_effect=AssertionError('Business writes are forbidden in the offline example')), \
             TestClient(app) as client:
            # Tool Calling output is a model fixture; ToolNode/API validation are real.
            model.invoke.return_value=AIMessage(content='',tool_calls=[{
                'name':'query_order_status','args':{'order_id':'DEMO_ORDER_1'},'id':'offline-tool-call'}])
            headers={'Authorization':'Bearer '+alice}
            for text in ['帮我查询订单状态','查询订单 DEMO_ORDER_1 的状态','查询订单 DEMO_ORDER_1 的物流']:
                response=client.post('/api/chat/stream',headers=headers,json={
                    'text':text,'conversation_id':conversation,'message_id':str(uuid4())})
                response.raise_for_status()
                events=[]; done=None
                for block in response.text.split('\n\n'):
                    lines=block.splitlines()
                    if not lines or not lines[0].startswith('event: '):continue
                    kind=lines[0][7:];events.append(kind)
                    if kind=='done':done=json.loads(next(s[6:] for s in lines if s.startswith('data: ')))
                if done is None:raise RuntimeError('SSE did not finish')
                turns.append({'events':events,'trace_id':done['trace_id'],
                    'reply':done['messages'][0]['text'],'tokens':done['metrics']['tokens'],
                    'spans':done['metrics']['spans']})
            own=client.get('/api/chat/history',params={'conversation_id':conversation},headers=headers)
            other=client.get('/api/chat/history',params={'conversation_id':conversation},
                             headers={'Authorization':'Bearer '+bob})
            own.raise_for_status();other.raise_for_status()
            # A second SQLite saver verifies serialized state, not just the in-memory API view.
            from my_agent.security import identity_scope
            with identity_scope('example_alice',alice):config=thread_config(conversation)
            saver=cp.make_checkpointer()
            restored=saver.get(config)
            saver.conn.close()
            restored_ok=bool(restored and len(own.json()['messages'])>=6)
        print(json.dumps({'mode':'offline-model-and-http-fixtures','live_model_calls':0,
            'business_writes':0,'history_restored':restored_ok,
            'other_user_history_empty':other.json()['messages']==[], 'turns':turns},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
