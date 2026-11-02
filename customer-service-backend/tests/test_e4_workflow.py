import json
import unittest
from unittest.mock import patch
from uuid import uuid4
import httpx
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from my_agent import nodes
from my_agent.intent import IntentResult
from my_agent.graph import graph

ORDER = 'C20260406001'


def reply(data, code=200):
    return httpx.Response(code, json={'code': 0, 'data': data}, request=httpx.Request('GET','http://test'))


def status(value='待发货'):
    return reply({'order_id': ORDER, 'status': value, 'status_desc': '测试状态说明'})


def read_status(value='待发货'):
    def get(url, **kwargs):
        if '/shipping-reminders/' in url:
            r=reply({},404)
            r.headers['X-Shipping-Protocol']='confirmed-idempotency-v1'
            return r
        return status(value)
    return get


def shipping_post(url, *, json, timeout):
    return reply({'request_type': 'shipping_reminder', 'request_id': json['request_id'],
                  'order_id': ORDER, 'status': 'submitted', 'status_desc': '发货提醒已创建'})


class TestBusinessFlow(unittest.TestCase):
    def state(self):
        return {'messages':[HumanMessage(content=f'帮我催发货 {ORDER}')],
                'intent_result':{'intent':'shipping_reminder','order_id':ORDER}}

    def prepare(self):
        with patch('httpx.get',side_effect=read_status()):
            result=nodes.business_node(self.state())
        return result['shipping_workflow']

    def invoke(self, thread, text):
        return graph.invoke({'messages':[HumanMessage(content=text)]},
                            {'configurable':{'thread_id':thread}})

    def test_prepare_queries_real_tool_without_write(self):
        with patch('httpx.get',side_effect=read_status()), patch('httpx.post') as post:
            result=nodes.business_node(self.state())
        self.assertEqual(result['shipping_workflow']['status'],'awaiting_confirmation')
        self.assertIn(f'确认催发货 {ORDER}',result['messages'][-1].content)
        post.assert_not_called()

    def test_ineligible_order_never_requests_confirmation(self):
        for value in ['运输中','已完成','已取消','未知状态']:
            with self.subTest(value=value), patch('httpx.get',side_effect=read_status(value)), patch('httpx.post') as post:
                result=nodes.business_node(self.state())
                self.assertEqual(result['shipping_workflow']['status'],'ineligible')
                post.assert_not_called()

    def test_logistics_returns_actual_trace(self):
        with patch('httpx.get',return_value=reply({'order_id':ORDER,'status':'运输中','status_desc':'已到测试站',
            'logistics_company':'测试物流','tracking_number':'TEST123','traces':[{'time':'2026-10-30T10:00:00','desc':'测试轨迹'}]})):
            result=nodes.logistics_node({'intent_result':{'intent':'logistics','order_id':ORDER}})
        self.assertIn('TEST123',result['messages'][-1].content)
        self.assertIn('测试轨迹',result['messages'][-1].content)

    @patch('my_agent.nodes.recognize_intent')
    def test_confirmation_submission_and_duplicate_are_persisted(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        thread=uuid4().hex
        writes=[]
        def post(*args,**kwargs):
            writes.append(kwargs['json']['request_id'])
            return shipping_post(*args,**kwargs)
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post',side_effect=post):
            first=self.invoke(thread,f'帮我催发货 {ORDER}')
            self.assertEqual(writes,[])
            result=self.invoke(thread,f'确认催发货 {ORDER}')
            self.assertEqual(result['shipping_workflow']['status'],'submitted')
            self.assertEqual(result['shipping_workflow']['result']['request_id'],writes[0])
            again=self.invoke(thread,f'确认催发货 {ORDER}')
            self.assertEqual(again['shipping_workflow']['status'],'submitted')
            self.assertEqual(len(writes),1)

    @patch('my_agent.nodes.recognize_intent')
    def test_continue_and_wrong_order_are_not_authorization(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        thread=uuid4().hex
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post') as post:
            first=self.invoke(thread,'催发货 '+ORDER)
            original=first['shipping_workflow']['request_id']
            for text in ['继续','确认催发货 A20260410001','是','确认']:
                result=self.invoke(thread,text)
                post.assert_not_called()
                self.assertEqual(result['shipping_workflow']['request_id'],original)

    @patch('my_agent.nodes.recognize_intent')
    def test_status_change_after_confirmation_blocks_write(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        thread=uuid4().hex
        with patch('httpx.get',side_effect=read_status()): self.invoke(thread,'催发货 '+ORDER)
        with patch('httpx.get',side_effect=read_status('运输中')),patch('httpx.post') as post:
            result=self.invoke(thread,'确认催发货 '+ORDER)
        self.assertEqual(result['shipping_workflow']['status'],'ineligible')
        post.assert_not_called()

    @patch('my_agent.nodes.recognize_intent')
    def test_unknown_outcome_reuses_id_after_fresh_confirmation(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        thread=uuid4().hex
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post',side_effect=httpx.ReadTimeout('timeout')):
            first=self.invoke(thread,'催发货 '+ORDER)
            result=self.invoke(thread,'确认催发货 '+ORDER)
        self.assertEqual(result['shipping_workflow']['status'],'outcome_unknown')
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post',side_effect=shipping_post):
            retry=self.invoke(thread,'确认催发货 '+ORDER)
        self.assertEqual(retry['shipping_workflow']['result']['request_id'],first['shipping_workflow']['request_id'])

    @patch('my_agent.nodes.recognize_intent')
    def test_cancel_invalidates_confirmation(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        thread=uuid4().hex
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post') as post:
            self.invoke(thread,'催发货 '+ORDER)
            intent.return_value=IntentResult(intent='cancel',reason='test')
            self.invoke(thread,'算了，不用了')
            result=self.invoke(thread,'确认催发货 '+ORDER)
        self.assertIsNone(result.get('shipping_workflow'))
        post.assert_not_called()

    def test_model_hallucinated_tool_target_is_replaced(self):
        wrong=AIMessage(content='',tool_calls=[{'name':'query_order_status','args':{'order_id':'A20260410001'},'id':'wrong'}])
        with patch('my_agent.nodes.llm_with_tools') as model:
            model.invoke.return_value=wrong
            result=nodes.call_model({'messages':[HumanMessage(content='查 '+ORDER)],
                'intent_result':{'intent':'order_status','order_id':ORDER}})
        self.assertEqual(result['messages'][0].tool_calls[0]['args'],{'order_id':ORDER})

    def test_tool_result_is_grounded_without_second_model_call(self):
        payload={'ok':True,'data':{'order_id':ORDER,'status':'待发货','status_desc':'真实说明'}}
        with patch('my_agent.nodes.llm_with_tools') as model:
            model.invoke.side_effect=AssertionError('must not synthesize facts')
            result=nodes.call_model({'messages':[ToolMessage(content=json.dumps(payload),tool_call_id='t')],
                'intent_result':{'intent':'order_status','order_id':ORDER}})
        self.assertIn('真实说明',result['messages'][0].content)


if __name__=='__main__': unittest.main()
