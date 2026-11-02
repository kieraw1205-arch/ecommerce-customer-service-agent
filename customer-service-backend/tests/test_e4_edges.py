import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from langchain_core.messages import HumanMessage
from my_agent import nodes, api_client
from my_agent.intent import IntentResult
from my_agent.graph import builder
from my_agent.checkpoint import make_checkpointer
from test_e4_workflow import ORDER, status, shipping_post, read_status


class TestE4Edges(unittest.TestCase):
    def prep(self):
        with patch('httpx.get',side_effect=read_status()):
            return nodes.business_node({'messages':[HumanMessage(content='催发货 '+ORDER)],
                'intent_result':{'intent':'shipping_reminder','order_id':ORDER}})['shipping_workflow']

    def confirm_state(self,workflow):
        return {'messages':[HumanMessage(content='确认催发货 '+ORDER)],'shipping_workflow':workflow,
                'intent_result':{'intent':'shipping_reminder','order_id':ORDER,'reason':'shipping_confirmation_control'}}

    def test_expired_confirmation_never_writes(self):
        workflow=self.prep();workflow['created_at']=time.time()-901
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post') as post:
            result=nodes.business_node(self.confirm_state(workflow))
        self.assertEqual(result['shipping_workflow']['status'],'expired')
        post.assert_not_called()

    def test_malformed_workflow_is_rejected(self):
        for workflow in [None,{}, {'version':1,'request_id':1}, {'version':99}]:
            with self.subTest(workflow=workflow),patch('httpx.post') as post:
                result=nodes.business_node(self.confirm_state(workflow))
                self.assertIsNone(result.get('shipping_workflow'))
                post.assert_not_called()

    def test_api_write_requires_strict_confirmation_and_expected_status(self):
        with patch('httpx.post') as post:
            for confirmation in [False,None,1,'true']:
                with self.subTest(confirmation=confirmation),self.assertRaises(ValueError):
                    api_client.create_shipping_reminder(ORDER,'U'+'1'*32,confirmed=confirmation,expected_status='待发货')
            with self.assertRaises(ValueError):
                api_client.create_shipping_reminder(ORDER,'U'+'1'*32,confirmed=True)
            post.assert_not_called()

    def test_unknown_outcome_replay_can_reconcile_after_shipping(self):
        workflow=self.prep();workflow['status']='outcome_unknown'
        with patch('httpx.get',side_effect=read_status('运输中')),patch('httpx.post',side_effect=shipping_post):
            result=nodes.business_node(self.confirm_state(workflow))
        self.assertEqual(result['shipping_workflow']['status'],'submitted')
        self.assertEqual(result['shipping_workflow']['result']['request_id'],workflow['request_id'])

    def test_committed_before_checkpoint_crash_is_reconciled_before_expiry(self):
        from test_e4_workflow import reply
        workflow=self.prep();workflow['created_at']=time.time()-901
        receipt={'request_type':'shipping_reminder','request_id':workflow['request_id'],
                 'order_id':ORDER,'status':'submitted','status_desc':'发货提醒已创建'}
        found=reply(receipt)
        found.headers['X-Shipping-Protocol']='confirmed-idempotency-v1'
        with patch('httpx.get',return_value=found),patch('httpx.post') as post:
            result=nodes.business_node(self.confirm_state(workflow))
        self.assertEqual(result['shipping_workflow']['status'],'submitted')
        self.assertEqual(result['shipping_workflow']['result'],receipt)
        post.assert_not_called()

    def test_old_backend_without_protocol_never_receives_post(self):
        from test_e4_workflow import reply
        workflow=self.prep()
        with patch('httpx.get',return_value=reply({},code=404)),patch('httpx.post') as post:
            result=nodes.business_node(self.confirm_state(workflow))
        self.assertNotEqual(result.get('shipping_workflow',workflow)['status'],'submitted')
        self.assertIn('版本',result['messages'][-1].content)
        post.assert_not_called()

    def test_unrecognized_conditions_and_cross_order_tasks_do_not_write(self):
        for condition,other in [('金额大于100',ORDER),('订单未发货','A20260410001')]:
            with self.subTest(condition=condition,other=other),patch('httpx.get') as get,patch('httpx.post') as post:
                result=nodes.business_node({'messages':[HumanMessage(content='test')], 'intent_result':{
                    'intent':'multi_intent','sub_intents':[{'intent':'order_status','order_id':ORDER},
                    {'intent':'shipping_reminder','order_id':other,'condition':condition}]}})
                self.assertIsNone(result.get('shipping_workflow'))
                get.assert_not_called();post.assert_not_called()

    def test_condition_unshipped_does_not_match_waiting_collection(self):
        with patch('httpx.get',side_effect=read_status('待揽收')):
            result=nodes.business_node({'messages':[HumanMessage(content='test')], 'intent_result':{
                'intent':'multi_intent','sub_intents':[{'intent':'order_status','order_id':ORDER},
                {'intent':'shipping_reminder','order_id':ORDER,'condition':'订单未发货'}]}})
        self.assertEqual(result['shipping_workflow']['status'],'ineligible')

    @patch('my_agent.nodes.recognize_intent')
    def test_switch_task_invalidates_previous_confirmation(self,intent):
        workflow=self.prep()
        intent.return_value=IntentResult(intent='order_status',order_id='A20260410001',reason='new request')
        result=nodes.recognize_intent_node({'messages':[HumanMessage(content='查另一笔订单 A20260410001')],
                                          'shipping_workflow':workflow})
        self.assertIsNone(result['shipping_workflow'])

    @patch('my_agent.nodes.recognize_intent')
    def test_missing_logistics_and_shipping_slot_supports_c_order(self,intent):
        for kind in ['logistics','shipping_reminder','order_status']:
            with self.subTest(kind=kind):
                result=nodes.recognize_intent_node({'messages':[HumanMessage(content=ORDER.lower())],
                    'pending_intent':{'intent':kind,'order_id':None}})
                self.assertEqual(result['intent_result']['order_id'],ORDER)
        intent.assert_not_called()

    @patch('my_agent.nodes.recognize_intent')
    def test_sqlite_recompile_preserves_confirmation_and_isolates_threads(self,intent):
        intent.return_value=IntentResult(intent='shipping_reminder',order_id=ORDER,reason='test')
        first_graph=builder.compile(checkpointer=make_checkpointer())
        config={'configurable':{'thread_id':'e4-restart-'+uuid4().hex}}
        with patch('httpx.get',side_effect=read_status()):
            first=first_graph.invoke({'messages':[HumanMessage(content='催发货 '+ORDER)]},config)
        # A distinct Python process must recover the same on-disk checkpoint.
        import subprocess, sys, json
        import my_agent.checkpoint as checkpoint
        script="""import sys,json,pathlib
import my_agent.checkpoint as cp
cp.DB_PATH=pathlib.Path(sys.argv[1])
from my_agent.graph import graph
s=graph.get_state({'configurable':{'thread_id':sys.argv[2]}}).values['shipping_workflow']
print(json.dumps({'status':s['status'],'request_id':s['request_id']}))
"""
        process=subprocess.run([sys.executable,'-c',script,str(checkpoint.DB_PATH),config['configurable']['thread_id']],
                               capture_output=True,text=True,check=True,timeout=20)
        recovered=json.loads(process.stdout)
        self.assertEqual(recovered,{'status':'awaiting_confirmation','request_id':first['shipping_workflow']['request_id']})
        restored=builder.compile(checkpointer=make_checkpointer())
        self.assertEqual(restored.get_state(config).values['shipping_workflow'],first['shipping_workflow'])
        other={'configurable':{'thread_id':uuid4().hex}}
        with patch('httpx.post') as post:
            stranger=restored.invoke({'messages':[HumanMessage(content='确认催发货 '+ORDER)]},other)
        self.assertIsNone(stranger.get('shipping_workflow'));post.assert_not_called()
        with patch('httpx.get',side_effect=read_status()),patch('httpx.post',side_effect=shipping_post):
            result=restored.invoke({'messages':[HumanMessage(content='确认催发货 '+ORDER)]},config)
        self.assertEqual(result['shipping_workflow']['result']['request_id'],first['shipping_workflow']['request_id'])


if __name__=='__main__': unittest.main()
