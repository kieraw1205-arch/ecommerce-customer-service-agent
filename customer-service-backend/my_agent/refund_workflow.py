"""Confirmed refund applications using existing API; approval is not implemented."""
import re,time
from uuid import uuid4
from my_agent.shipping_workflow import latest_text,message
from my_agent.tools import query_order_status
from my_agent.api_client import get_refund_application,create_refund_application,BusinessAPIError
from my_agent.contracts import identifier

def control_intent(state):
    text=latest_text(state);workflow=state.get('refund_workflow');pending=state.get('pending_intent') or {}
    if text.startswith('确认退款'):
        return {'intent_result':{'intent':'refund','order_id':workflow.get('order_id') if isinstance(workflow,dict) else None,
                                'reason':'refund_confirmation_control'}}
    if pending.get('intent')=='refund':
        if re.fullmatch(r'[A-Z]\d{11}',text.upper()):
            return {'intent_result':{**pending,'order_id':text.upper()},'pending_intent':None}
        match=re.fullmatch(r'退款原因[:：]\s*(.+)',text)
        if match:return {'intent_result':{**pending,'refund_reason':match[1].strip()},'pending_intent':None}
    return None

def valid(workflow):
    try:
        return (isinstance(workflow,dict) and workflow['version']==1 and identifier(workflow['order_id'])
          and bool(re.fullmatch(r'R[0-9a-f]{32}',workflow['request_id'])) and isinstance(workflow['refund_reason'],str)
          and 0<len(workflow['refund_reason'].strip())<=255 and type(workflow['created_at']) in {int,float}
          and isinstance(workflow['checked_status'],str) and workflow['status'] in {
              'awaiting_confirmation','submitted','outcome_unknown','expired','failed','conflict'})
    except (KeyError,TypeError,ValueError):return False

def prepare(result):
    order=result.get('order_id');reason=result.get('refund_reason')
    if not order:return message('请提供需要申请退款的订单号。',pending_intent={'intent':'refund','refund_reason':reason},refund_workflow=None)
    if not isinstance(reason,str) or not reason.strip():
        return message('请说明退款原因，回复“退款原因：具体原因”。',pending_intent={'intent':'refund','order_id':order},refund_workflow=None)
    if len(reason.strip())>255:return message('退款原因请控制在 255 字以内。',refund_workflow=None)
    outcome=query_order_status.invoke({'order_id':order})
    if not outcome['ok']:return message(outcome['error']['message']+' 尚未提交退款申请。',refund_workflow=None)
    workflow={'version':1,'order_id':order,'refund_reason':reason.strip(),'request_id':'R'+uuid4().hex,
              'created_at':time.time(),'checked_status':outcome['data']['status'],'status':'awaiting_confirmation'}
    return message(f"订单 {order} 当前状态：{workflow['checked_status']}。退款原因：{workflow['refund_reason']}。"
                   f"申请提交后仍需审核，不代表退款成功。请在15分钟内回复“确认退款 {order}”。",refund_workflow=workflow,pending_intent=None)

def confirm(state):
    workflow=state.get('refund_workflow')
    if not valid(workflow):return message('没有可确认的有效退款任务，请重新提出申请。',refund_workflow=None)
    workflow=dict(workflow)
    if workflow['status']=='submitted':return message('该退款申请已提交，申请编号：'+workflow['result']['request_id']+'。未重复提交。')
    if latest_text(state)!='确认退款 '+workflow['order_id']:
        return message('尚未获得本订单的明确退款确认，请回复“确认退款 '+workflow['order_id']+'”。')
    try:receipt=get_refund_application(workflow['order_id'],workflow['request_id'])
    except BusinessAPIError as exc:return message(str(exc)+' 原申请结果待核实，未进行新的提交。')
    if receipt is not None:
        workflow.update(status='submitted',result=receipt)
        return message('已核实原申请：'+receipt['status_desc']+' 申请编号：'+receipt['request_id'],refund_workflow=workflow)
    if workflow['status'] not in {'awaiting_confirmation','outcome_unknown'}:return message('此退款任务已结束，请重新提出需求。')
    retry=workflow['status']=='outcome_unknown'
    if not retry and not 0<=time.time()-workflow['created_at']<=900:
        workflow['status']='expired';return message('退款确认已过期，请重新提出申请。',refund_workflow=workflow)
    if not retry:
        outcome=query_order_status.invoke({'order_id':workflow['order_id']})
        if not outcome['ok']:return message(outcome['error']['message']+' 未进行新的提交。')
        if outcome['data']['status']!=workflow['checked_status']:
            workflow['status']='failed';return message('订单状态已变化，请重新查询并确认退款申请。',refund_workflow=workflow)
    try:
        receipt=create_refund_application(workflow['order_id'],workflow['request_id'],reason=workflow['refund_reason'],
                                         expected_status=workflow['checked_status'],confirmed=True)
    except BusinessAPIError as exc:
        workflow['status']='outcome_unknown' if exc.kind=='outcome_unknown' else 'conflict' if exc.kind=='conflict' else 'failed'
        workflow['error']={'kind':exc.kind,'message':str(exc)}
        return message(str(exc)+' 未确认退款成功；可使用原任务标识核实。',refund_workflow=workflow)
    workflow.update(status='submitted',result=receipt)
    return message(receipt['status_desc']+' 申请编号：'+receipt['request_id']+'。提交申请不代表退款完成。',refund_workflow=workflow)

def handle(state):
    result=state.get('intent_result') or {};workflow=state.get('refund_workflow')
    if result.get('reason')=='refund_confirmation_control':return confirm(state)
    if valid(workflow) and workflow['order_id']==result.get('order_id') and workflow['status'] in {'awaiting_confirmation','submitted','outcome_unknown'}:
        return confirm(state)
    return prepare(result)
