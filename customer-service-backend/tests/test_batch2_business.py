import unittest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
import httpx
from my_agent import nodes

ORDER='A20261030001'; PRODUCT='SKU_TEST_001'

def response(data,code=200,header=None):
    r=httpx.Response(code,json={'code':0,'data':data},request=httpx.Request('GET','http://test'))
    if header:r.headers.update(header)
    return r

def get(url,**kwargs):
    if '/refund-applications/' in url:return response({},404,{'X-Refund-Protocol':'confirmed-idempotency-v1'})
    if '/products/' in url:return response({'product_id':PRODUCT,'title':'测试保温杯','description':'测试杯具',
        'price':'99.00','stock_status':'有货','cover_url':None,'attributes':{'容量':'500ml'}})
    return response({'order_id':ORDER,'status':'待发货','status_desc':'测试备货'})

def post(url,**kwargs):
    body=kwargs['json']
    return response({'request_type':'refund_application','request_id':body['request_id'],'order_id':ORDER,
                    'status':'submitted','status_desc':'退款申请已提交，正在审核中。'})

class TestAgentBusiness(unittest.TestCase):
    def state(self,text='申请退款',**fields):
        return {'messages':[HumanMessage(content=text)],'intent_result':{'intent':'refund','order_id':ORDER,
            'refund_reason':'不需要了',**fields}}

    def test_refund_preparation_requires_confirmation(self):
        with patch('httpx.get',side_effect=get),patch('httpx.post') as write:
            result=nodes.business_node(self.state())
        self.assertEqual(result['refund_workflow']['status'],'awaiting_confirmation')
        self.assertIn('确认退款 '+ORDER,result['messages'][-1].content)
        write.assert_not_called()

    def test_refund_reason_is_not_classifier_reason(self):
        with patch('httpx.get',side_effect=get),patch('httpx.post') as write:
            result=nodes.business_node(self.state(refund_reason=None,reason='分类原因，不是用户退款原因'))
        self.assertEqual(result['pending_intent']['intent'],'refund')
        self.assertIn('退款原因',result['messages'][-1].content)
        write.assert_not_called()

    def test_refund_submission_and_receipt_saved(self):
        with patch('httpx.get',side_effect=get):workflow=nodes.business_node(self.state())['refund_workflow']
        state=self.state('确认退款 '+ORDER,reason='refund_confirmation_control');state['refund_workflow']=workflow
        with patch('httpx.get',side_effect=get),patch('httpx.post',side_effect=post):result=nodes.business_node(state)
        self.assertEqual(result['refund_workflow']['status'],'submitted')
        self.assertEqual(result['refund_workflow']['result']['request_id'],workflow['request_id'])
        self.assertNotIn('退款已完成',result['messages'][-1].content)

    def test_product_answer_is_grounded_in_existing_api(self):
        state={'messages':[HumanMessage(content='SKU_TEST_001容量是多少？')],
               'intent_result':{'intent':'product_qa','product_id':PRODUCT}}
        with patch('httpx.get',side_effect=get):result=nodes.knowledge_node(state)
        self.assertIn('500ml',result['messages'][-1].content)
        self.assertIn('SKU_TEST_001',result['messages'][-1].content)

    def test_product_unknown_policy_is_not_invented(self):
        state={'messages':[HumanMessage(content='SKU_TEST_001支持七天无理由吗？')],
               'intent_result':{'intent':'product_qa','product_id':PRODUCT}}
        with patch('httpx.get',side_effect=get):result=nodes.knowledge_node(state)
        self.assertIn('未提供',result['messages'][-1].content)
        self.assertNotIn('支持七天无理由',result['messages'][-1].content)

    def test_product_slot_is_requested(self):
        result=nodes.knowledge_node({'messages':[HumanMessage(content='这个产品容量？')],
                                    'intent_result':{'intent':'product_qa'}})
        self.assertEqual(result['pending_intent']['intent'],'product_qa')

    def test_string_none_is_not_a_refund_reason(self):
        from my_agent.intent import IntentResult
        for value in ['None','null','', '  None  ']:
            parsed=IntentResult(intent='refund',order_id=ORDER,refund_reason=value,reason='classifier')
            self.assertIsNone(parsed.refund_reason)

    def test_condition_synonym_is_checked_but_not_written(self):
        state=self.state('查状态，如果还没发货就催单',intent='multi_intent',sub_intents=[
            {'intent':'order_status','order_id':ORDER},
            {'intent':'shipping_reminder','order_id':ORDER,'condition':'订单还没发货'}])
        with patch('httpx.get',side_effect=get),patch('httpx.post') as write:result=nodes.business_node(state)
        self.assertEqual(result['shipping_workflow']['status'],'awaiting_confirmation')
        write.assert_not_called()

    def test_compound_two_order_reads_execute_and_preserve_plan(self):
        def read(url,**kwargs):
            oid=url.split('/orders/')[1].split('/')[0]
            return response({'order_id':oid,'status':'待发货' if oid==ORDER else '运输中','status_desc':'fixture'})
        state=self.state('查两笔订单',intent='multi_intent',order_id=None,sub_intents=[
            {'intent':'order_status','order_id':ORDER},{'intent':'order_status','order_id':'A20261030002'}])
        with patch('httpx.get',side_effect=read),patch('httpx.post') as write:result=nodes.business_node(state)
        self.assertIn('待发货',result['messages'][-1].content);self.assertIn('运输中',result['messages'][-1].content)
        self.assertEqual(len(result['pending_workflow']['tasks']),2);write.assert_not_called()

    @patch('my_agent.nodes.recognize_intent')
    def test_explicit_new_status_query_drops_model_stale_tasks(self,model):
        from my_agent.intent import IntentResult,SubIntent
        model.return_value=IntentResult(intent='multi_intent',reason='stale model plan',sub_intents=[
            SubIntent(intent='shipping_reminder',order_id=ORDER),SubIntent(intent='order_status',order_id='A20261030002')])
        result=nodes.recognize_intent_node({'messages':[HumanMessage(content='另外帮我查订单 A20261030002 状态。')],
             'pending_workflow':{'status':'pending','current_step':0,'tasks':[{'intent':'shipping_reminder','order_id':ORDER}]}})
        self.assertEqual(result['intent_result']['intent'],'order_status')
        self.assertEqual(result['intent_result']['order_id'],'A20261030002')
        self.assertIsNone(result['pending_workflow'])

    @patch('my_agent.nodes.recognize_intent')
    def test_negated_task_switch_does_not_force_a_query(self,model):
        from my_agent.intent import IntentResult
        model.return_value=IntentResult(intent='cancel',reason='user does not want query')
        result=nodes.recognize_intent_node({'messages':[HumanMessage(content='另外帮我不要查订单 A20261030002 状态了')]})
        self.assertEqual(result['intent_result']['intent'],'cancel')

if __name__=='__main__':unittest.main()
