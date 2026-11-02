"""Constrain model-selected tools to the recognized target and render API facts."""
import json
from uuid import uuid4
from my_agent.telemetry import TelemetryCallback
from langchain_core.messages import AIMessage, ToolMessage


def render(payload, intent):
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        error = payload.get('error', {}) if isinstance(payload, dict) else {}
        return error.get('message', '查询结果异常，暂时无法确认。')
    data = payload['data']
    if intent == 'order_list':
        orders = data['orders']
        if not orders:
            return f"用户 {data['user_id']} 暂无订单。"
        return f"用户 {data['user_id']} 最近最多 5 笔订单：\n" + '\n'.join(
            f"{item['order_id']}｜{item['title']}｜{item['status']}｜金额 {item['amount']}" for item in orders)
    if intent == 'logistics':
        lines = [f"订单 {data['order_id']}：{data['status']}；{data['status_desc']}",
                 f"物流公司：{data['logistics_company']}；运单号：{data['tracking_number']}"]
        lines += [f"{trace['time']} {trace['desc']}" for trace in sorted(data['traces'], key=lambda t: t['time'], reverse=True)]
        if not data['traces']:
            lines.append('暂无物流轨迹，以上为业务接口返回的物流信息。')
        return '\n'.join(lines)
    return f"订单 {data['order_id']}：{data['status']}；{data['status_desc']}"


def query_turn(state, model, system):
    intent = state.get('intent_result') or {}
    messages = state['messages']
    if isinstance(messages[-1], ToolMessage):
        try:
            content = render(json.loads(messages[-1].content), intent.get('intent'))
        except (ValueError, TypeError, KeyError):
            content = '业务接口返回数据异常，暂时无法确认查询结果。'
        return {'messages': [AIMessage(content=content)]}
    name, args = ('query_user_orders', {'user_id': intent.get('user_id')}) if intent.get('intent') == 'order_list' else (
                 'query_order_status', {'order_id': intent.get('order_id')})
    try:
        answer = model.invoke([system] + messages, config={"callbacks": [TelemetryCallback()]})
        calls = answer.tool_calls
        if len(calls) == 1 and calls[0]['name'] == name and calls[0]['args'] == args:
            return {'messages': [answer]}
    except Exception:
        pass
    # A model omission, timeout, or changed target cannot suppress the real read.
    return {'messages': [AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': uuid4().hex}])]}
