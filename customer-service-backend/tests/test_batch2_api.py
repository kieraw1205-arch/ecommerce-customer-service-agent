import importlib.util,json,os,secrets,unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
import httpx
from my_agent.intent import IntentResult

class TestAgentAPI(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('my_agent.app'),'authenticated Agent API is not implemented')
        from my_agent.app import app
        self.alice_token=secrets.token_urlsafe(24);self.bob_token=secrets.token_urlsafe(24)
        mapping={self.alice_token:'u_test_alice',self.bob_token:'u_test_bob'}
        self.env=patch.dict(os.environ,{'AGENT_AUTH_TOKENS_JSON':json.dumps(mapping)})
        self.env.start();self.addCleanup(self.env.stop)
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer '+self.alice_token}
        self.conversation=str(uuid4());self.message=str(uuid4())

    def body(self):return {'conversation_id':self.conversation,'message_id':self.message,'text':'查询订单 A20261030001 状态'}

    def get(self,url,**kwargs):
        self.assertEqual(kwargs['headers']['Authorization'],'Bearer '+self.alice_token)
        return httpx.Response(200,json={'code':0,'data':{'order_id':'A20261030001','status':'待发货','status_desc':'真实测试数据'}},
                              request=httpx.Request('GET',url))

    def test_auth_and_request_validation(self):
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertEqual(self.client.get('/api/me',headers=self.headers).json()['user_id'],'u_test_alice')
        body={**self.body(),'sender_id':'u_test_bob'}
        self.assertEqual(self.client.post('/api/chat',headers=self.headers,json=body).status_code,422)

    @patch('my_agent.nodes.recognize_intent')
    def test_identity_scoped_history_and_message_idempotency(self,intent):
        intent.return_value=IntentResult(intent='order_status',order_id='A20261030001',reason='test')
        with patch('httpx.get',side_effect=self.get):
            first=self.client.post('/api/chat',headers=self.headers,json=self.body())
            duplicate=self.client.post('/api/chat',headers=self.headers,json=self.body())
        self.assertEqual(first.status_code,200)
        self.assertIn('真实测试数据',first.json()['messages'][0]['text'])
        self.assertTrue(duplicate.json()['cached'])
        self.assertEqual(intent.call_count,1)
        self.assertEqual(first.headers['X-Trace-ID'],first.json()['trace_id'])
        own=self.client.get('/api/chat/history',params={'conversation_id':self.conversation},headers=self.headers)
        other=self.client.get('/api/chat/history',params={'conversation_id':self.conversation},headers={'Authorization':'Bearer '+self.bob_token})
        self.assertGreater(len(own.json()['messages']),0);self.assertEqual(other.json()['messages'],[])

    @patch('my_agent.nodes.recognize_intent')
    def test_sse_contains_actual_progress_reply_and_done(self,intent):
        intent.return_value=IntentResult(intent='order_status',order_id='A20261030001',reason='test')
        with patch('httpx.get',side_effect=self.get):
            response=self.client.post('/api/chat/stream',headers=self.headers,json=self.body())
        self.assertEqual(response.status_code,200)
        self.assertIn('text/event-stream',response.headers['content-type'])
        for event in ['trace','node','reply','done']:self.assertIn('event: '+event,response.text)
        self.assertIn('真实测试数据',response.text)

if __name__=='__main__':unittest.main()
