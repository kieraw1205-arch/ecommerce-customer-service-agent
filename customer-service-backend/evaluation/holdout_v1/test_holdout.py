import copy
import unittest

import input_validation as worker

class InputSeparationTests(unittest.TestCase):
    def good(self):return {'version':'holdout-v1','cases':[{'id':'H01','actor':'alice','turns':[{'text':'查订单'}]}]}
    def test_accepts_only_unlabeled_inputs(self):self.assertEqual(len(worker.validate_inputs(self.good())),1)
    def test_rejects_expected_label_injection(self):
        case=self.good();case['cases'][0]['expected']={'intent':'order_status'}
        with self.assertRaises(ValueError):worker.validate_inputs(case)
    def test_rejects_root_labels(self):
        case=self.good();case['labels']=[]
        with self.assertRaises(ValueError):worker.validate_inputs(case)
    def test_rejects_duplicate_case_or_replay_without_prior_turn(self):
        case=self.good();case['cases'].append(copy.deepcopy(case['cases'][0]))
        with self.assertRaises(ValueError):worker.validate_inputs(case)
        case=self.good();case['cases'][0]['turns'][0]['reuse_previous_message_id']=True
        with self.assertRaises(ValueError):worker.validate_inputs(case)

class ScoringTests(unittest.TestCase):
    def test_wilson_interval_and_empty_sample(self):
        from score import wilson
        self.assertIsNone(wilson(0,0))
        lo,hi=wilson(24,24);self.assertGreater(lo,.86);self.assertEqual(hi,1)
        lo,hi=wilson(0,24);self.assertEqual(lo,0);self.assertLess(hi,.14)
    def test_self_declared_success_is_not_accepted(self):
        from score import grade
        case={'id':'H01','category':['write'],'input':{'message':'confirm'},'expected':{'intent':'refund','success':{'checks':[{'path':'facts.total_writes','op':'eq','value':1}]}}}
        result=grade([case],[{'id':'H01','capabilities':['intent','slots','tools','task'],'prediction':{'intent':'refund','output':'操作成功','facts':{'total_writes':0}}}])
        self.assertEqual(result['metrics']['task_success']['correct'],0)
    def test_tool_args_and_runtime_error_remain_in_denominator(self):
        from score import grade
        case={'id':'H01','category':['query'],'input':{'message':'query'},'expected':{'intent':'order_status','order_id':'A1','tool_calls':[{'name':'query','args':{'order_id':'A1'}}],'success':{'checks':[{'path':'facts.total_writes','op':'eq','value':0}]}}}
        record={'id':'H01','capabilities':['intent','slots','tools','task'],'prediction':{'intent':'order_status','order_id':'A1','tool_calls':[{'name':'query','args':{'order_id':'OTHER'}}],'facts':{'total_writes':0}}}
        result=grade([case],[record]);self.assertEqual(result['metrics']['tool_call_accuracy']['correct'],0)
        record['error']='TimeoutError';result=grade([case],[record]);self.assertEqual(result['metrics']['task_success']['denominator'],1);self.assertEqual(result['metrics']['task_success']['correct'],0)
    def test_no_executed_records_cannot_be_a_success(self):
        from score import grade
        case={'id':'H01','category':['query'],'input':{'message':'query'},'expected':{'intent':'order_status','success':{'checks':[{'path':'output','op':'contains','value':'ready'}]}}}
        result=grade([case],[]);self.assertEqual(result['coverage']['scenarios']['executed'],0);self.assertIsNone(result['metrics']['task_success']['rate'])

if __name__=='__main__':unittest.main()
