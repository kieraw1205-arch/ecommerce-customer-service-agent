"""Execute bounded read batches and prepare at most one confirmed refund."""
from my_agent.tools import query_order_status,query_order_logistics
from my_agent.query_flow import render
from my_agent.shipping_workflow import message

def handle(state):
    result=state.get('intent_result') or {};tasks=result.get('sub_intents') or []
    allowed={'order_status','logistics','refund'}
    if not 1<=len(tasks)<=5 or any(t.get('intent') not in allowed or t.get('condition') for t in tasks):return None
    if sum(t.get('intent')=='refund' for t in tasks)>1:return None
    if any(not (t.get('order_id') or result.get('order_id')) for t in tasks):
        return message('请明确每个子任务的订单号，尚未执行业务操作。')
    lines=[];updates={}
    for task in tasks:
        kind=task['intent'];oid=task.get('order_id') or result.get('order_id')
        if kind=='refund':
            from my_agent.refund_workflow import handle as refund
            outcome=refund({**state,'intent_result':{'intent':'refund','order_id':oid,
                'refund_reason':task.get('refund_reason') or result.get('refund_reason')}})
            lines.extend(m.content for m in outcome.pop('messages'));updates.update(outcome)
        else:
            tool=query_order_status if kind=='order_status' else query_order_logistics
            lines.append(render(tool.invoke({'order_id':oid}),kind))
    prefix='我们继续之前的任务计划。\n' if result.get('reason')=='用户希望继续之前保存的复合任务' else ''
    return message(prefix+'\n'.join(lines),**updates)
