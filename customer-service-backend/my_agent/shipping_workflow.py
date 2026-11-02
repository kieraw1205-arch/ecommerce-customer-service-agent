"""Deterministic confirmation boundary for the existing shipping-reminder API."""
import re
import time
from uuid import uuid4
from langchain_core.messages import AIMessage, HumanMessage
from my_agent.api_client import create_shipping_reminder, get_shipping_reminder, BusinessAPIError
from my_agent.contracts import identifier
from my_agent.tools import query_order_status

CONFIRM_TTL = 900
CONDITIONS = {'eligible': {'待发货', '待揽收'}, 'unshipped': {'待发货'}}
UNSHIPPED = {'订单还没发货', '还没发货', '订单没有发货', '没有发货', '尚未发货', '订单尚未发货时', '订单未发货时', '订单未发货', '未发货', '如果未发货', '如果订单未发货', '订单尚未发货', '待发货', '订单待发货'}


def latest_text(state):
    return next((m.content.strip() for m in reversed(state.get('messages', []))
                 if isinstance(m, HumanMessage) and isinstance(m.content, str)), '')


def message(text, **updates):
    return {'messages': [AIMessage(content=text)], **updates}


def valid_workflow(workflow):
    if not isinstance(workflow, dict) or workflow.get('version') != 1:
        return False
    try:
        identifier(workflow['order_id'])
        return (bool(re.fullmatch(r'U[0-9a-f]{32}', workflow['request_id']))
                and workflow['condition'] in CONDITIONS
                and type(workflow['created_at']) in {int, float}
                and workflow['status'] in {'awaiting_confirmation', 'submitted', 'ineligible',
                    'check_failed', 'outcome_unknown', 'conflict', 'expired', 'failed'})
    except (KeyError, TypeError, ValueError):
        return False


def confirmation_prompt(workflow):
    return (f"订单 {workflow['order_id']} 符合本次催发货条件。"
            f"如需提交，请明确回复“确认催发货 {workflow['order_id']}”。确认在 15 分钟内有效。")


def control_intent(state):
    """Only human text can request confirmation; model labels confer no authority."""
    text = latest_text(state)
    workflow = state.get('shipping_workflow')
    if text.startswith('确认催发货'):
        return {'intent_result': {'intent': 'shipping_reminder', 'order_id':
                    (re.fullmatch(r'确认催发货\s+([A-Za-z0-9_-]{1,64})',text).group(1) if re.fullmatch(r'确认催发货\s+([A-Za-z0-9_-]{1,64})',text) else None),
                    'reason': 'shipping_confirmation_control'}}
    if text in {'算了', '算了，不用了', '不用了', '取消催发货', '取消刚才的请求', '停止当前任务'}:
        return {'intent_result': {'intent': 'cancel', 'reason': 'human_cancel'},
                'pending_intent': None, 'pending_workflow': None, 'shipping_workflow': None}
    if valid_workflow(workflow) and workflow['status'] in {'awaiting_confirmation', 'outcome_unknown'}:
        if text in {'继续', '继续吧', '继续处理', '是', '确认', '好', '好的'} and not state.get('pending_workflow'):
            return {'intent_result': {'intent': 'shipping_reminder', 'order_id': workflow['order_id'],
                                     'reason': 'shipping_confirmation_control'}}
    pending = state.get('pending_intent') or {}
    if pending.get('intent') in {'logistics', 'shipping_reminder'} and re.fullmatch(r'[A-Z]\d{11}', text.upper()):
        return {'intent_result': {**pending, 'order_id': text.upper()}, 'pending_intent': None}
    if pending.get('intent') == 'order_list' and re.fullmatch(r'u\d{1,63}', text):
        return {'intent_result': {**pending, 'user_id': text}, 'pending_intent': None}
    return None


def prepare(order_id, condition='eligible'):
    if not order_id:
        return message('请提供需要催发货的订单号。', pending_intent={'intent': 'shipping_reminder'}, shipping_workflow=None)
    try:
        identifier(order_id)
    except ValueError:
        return message('订单号格式无效，请重新提供。', shipping_workflow=None)
    workflow = {'version': 1, 'order_id': order_id, 'condition': condition,
                'request_id': 'U' + uuid4().hex, 'created_at': time.time(), 'status': 'check_failed'}
    outcome = query_order_status.invoke({'order_id': order_id})
    if not outcome['ok']:
        return message(outcome['error']['message'] + ' 尚未提交催发货。', shipping_workflow=workflow)
    data = outcome['data']
    workflow['checked_status'] = data['status']
    if data['status'] not in CONDITIONS[condition]:
        workflow['status'] = 'ineligible'
        return message(f"订单 {order_id} 当前状态：{data['status']}；{data['status_desc']}。"
                       '不符合本次催发货条件，未提交申请。', shipping_workflow=workflow)
    workflow['status'] = 'awaiting_confirmation'
    return message(f"订单状态：{data['status']}；{data['status_desc']}。" + confirmation_prompt(workflow), shipping_workflow=workflow)


def confirm(state):
    workflow = state.get('shipping_workflow')
    if not valid_workflow(workflow):
        return message('没有可确认的有效催发货任务，请重新提出需求。', shipping_workflow=None)
    workflow = dict(workflow)
    if workflow['status'] == 'submitted':
        result = workflow.get('result') or {}
        return message(f"此请求已提交，申请编号：{result.get('request_id', workflow['request_id'])}。未重复提交。")
    if latest_text(state) != f"确认催发货 {workflow['order_id']}":
        return message('尚未获得本订单的明确确认。' + confirmation_prompt(workflow))
    # Reconcile before TTL/state guards: a previous POST may have committed just
    # before the worker died and therefore never reached its Graph checkpoint.
    try:
        receipt = get_shipping_reminder(workflow['order_id'], workflow['request_id'])
    except BusinessAPIError as exc:
        return message(str(exc) + ' 未执行新的提交，已有申请结果仍待核实。')
    if receipt is not None:
        workflow['status'] = 'submitted'
        workflow['result'] = receipt
        return message(f"已核实原申请：{receipt['status_desc']} 申请编号：{receipt['request_id']}。", shipping_workflow=workflow)
    if workflow['status'] not in {'awaiting_confirmation', 'outcome_unknown'}:
        return message('此催发货任务已结束或不符合条件，请重新提出需求。')
    retry_unknown = workflow['status'] == 'outcome_unknown'
    if not retry_unknown and not 0 <= time.time() - workflow['created_at'] <= CONFIRM_TTL:
        workflow['status'] = 'expired'
        return message('确认已过期，请重新查询并申请催发货。', shipping_workflow=workflow)
    # A timed-out submission may already exist; retry its original id to reconcile,
    # even if the order has since shipped. The API checks replay before eligibility.
    if not retry_unknown:
        outcome = query_order_status.invoke({'order_id': workflow['order_id']})
        if not outcome['ok']:
            return message(outcome['error']['message'] + ' 未提交催发货，请稍后重新确认。')
        workflow['checked_status'] = outcome['data']['status']
        if outcome['data']['status'] not in CONDITIONS[workflow['condition']]:
            workflow['status'] = 'ineligible'
            return message('订单状态已变化，不符合本次催发货条件，未提交申请。', shipping_workflow=workflow)
    try:
        result = create_shipping_reminder(workflow['order_id'], workflow['request_id'], confirmed=True, expected_status=workflow.get('checked_status'))
    except BusinessAPIError as exc:
        workflow['status'] = {'outcome_unknown': 'outcome_unknown', 'conflict': 'conflict',
                              'ineligible': 'ineligible'}.get(exc.kind, 'failed')
        workflow['error'] = {'kind': exc.kind, 'message': str(exc)}
        suffix = f" 如需核实，请再次回复“确认催发货 {workflow['order_id']}”，将复用原请求标识。" if exc.kind == 'outcome_unknown' else ''
        return message(str(exc) + suffix, shipping_workflow=workflow)
    workflow['status'] = 'submitted'
    workflow['result'] = result
    return message(f"{result['status_desc']} 申请编号：{result['request_id']}。", shipping_workflow=workflow)


def handle_business(state, legacy):
    result = state.get('intent_result') or {}
    if result.get('reason') == 'shipping_confirmation_control':
        return confirm(state)
    if result.get('intent') == 'shipping_reminder':
        previous = state.get('shipping_workflow')
        if valid_workflow(previous) and previous['order_id'] == result.get('order_id') and previous['status'] in {'awaiting_confirmation', 'outcome_unknown', 'submitted'}:
            return confirm(state)
        return prepare(result.get('order_id'))
    if result.get('intent') != 'multi_intent':
        return legacy
    tasks = result.get('sub_intents', [])
    if [task.get('intent') for task in tasks] != ['order_status', 'shipping_reminder']:
        return legacy
    ids = {task.get('order_id') or result.get('order_id') for task in tasks}
    if len(ids) != 1 or None in ids or tasks[0].get('condition'):
        return {**legacy, **message('复合任务的订单或查询条件不明确，尚未执行。', shipping_workflow=None)}
    condition = tasks[1].get('condition')
    normalized = re.sub(r'[\s，,。！!？?：:]', '', condition) if isinstance(condition, str) else None
    if normalized not in UNSHIPPED:
        return {**legacy, **message('该复合任务的条件尚不支持自动判断，尚未执行。', shipping_workflow=None)}
    previous = state.get('shipping_workflow')
    if valid_workflow(previous) and previous['order_id'] in ids and previous['status'] in {'awaiting_confirmation', 'outcome_unknown', 'submitted'}:
        update = confirm(state)
    else:
        update = prepare(next(iter(ids)), condition='unshipped')
    if result.get('reason') == '用户希望继续之前保存的复合任务':
        update['messages'][0].content = '我们继续之前的任务计划。' + update['messages'][0].content
    return {**legacy, **update}
