"""Authenticated application adapter around the existing compiled Graph."""
import hashlib,threading
from uuid import uuid4
from langchain_core.messages import HumanMessage,AIMessage
from my_agent.graph import graph
from my_agent.security import current_principal
from my_agent.telemetry import trace_scope
from my_agent.audit import capture_calls

_locks=[threading.RLock() for _ in range(64)]

def thread_config(conversation_id):
    principal=current_principal()
    value=hashlib.sha256((principal.user_id+':'+str(conversation_id)).encode()).hexdigest()
    return {'configurable':{'thread_id':'user-'+value}}

def history(conversation_id):
    state=graph.get_state(thread_config(conversation_id)).values
    return [{'role':'human' if isinstance(m,HumanMessage) else 'ai','text':m.content}
            for m in state.get('messages',[]) if isinstance(m,(HumanMessage,AIMessage))
            and isinstance(m.content,str) and m.content and not getattr(m,'tool_calls',None)]

def safe_state(state):
    return {key:state.get(key) for key in ['intent_result','pending_intent','pending_workflow','shipping_workflow','refund_workflow']}

def execute(text,conversation_id,message_id=None,*,trace_id=None,emit=None):
    message_id=str(message_id or uuid4());conversation_id=str(conversation_id)
    config=thread_config(conversation_id);key=config['configurable']['thread_id']
    events=emit or (lambda kind,data:None)
    with _locks[int(key[-4:],16)%len(_locks)],trace_scope(trace_id) as trace,capture_calls() as calls:
        events('trace',{'trace_id':trace.trace_id})
        previous=graph.get_state(config).values
        receipts=dict(previous.get('request_receipts') or {})
        cached=receipts.get(message_id)
        if cached:
            if cached['text_hash']!=hashlib.sha256(text.encode()).hexdigest():
                raise ValueError('message_id already used with different text')
            result={**cached['response'],'cached':True,'trace_id':trace.trace_id}
        else:
            node_names={'intent':'recognize_intent_node','agent':'call_model','clarify':'clarify_node',
                'business':'business_node','logistics':'logistics_node','knowledge':'knowledge_node',
                'chat':'chat_node','unsupported':'unsupported_node','cancel':'cancel_node'}
            for update in graph.stream({'messages':[HumanMessage(content=text,id=message_id)]},config,stream_mode='updates'):
                for name in update:
                    spans=trace.summary()['spans']
                    matching=[s for s in spans if s['name']==node_names.get(name) or name=='tools' and s['kind']=='tool']
                    events('node',{'name':name,'duration_ms':matching[-1]['duration_ms'] if matching else None})
            state=graph.get_state(config).values
            reply=next((m.content for m in reversed(state.get('messages',[])) if isinstance(m,AIMessage)
                       and isinstance(m.content,str) and m.content and not m.tool_calls),'暂时无法完成请求。')
            result={'conversation_id':conversation_id,'trace_id':trace.trace_id,'messages':[{'text':reply}],
                    'cached':False,'workflows':{k:state.get(k) for k in ['shipping_workflow','refund_workflow']}}
            receipts[message_id]={'text_hash':hashlib.sha256(text.encode()).hexdigest(),'response':result}
            if len(receipts)>100:receipts.pop(next(iter(receipts)))
            graph.update_state(config,{'request_receipts':receipts})
        state=graph.get_state(config).values
        evidence={'state':safe_state(state),'tool_calls':list(calls)}
    result['metrics']=trace.summary()
    events('reply',{'text':result['messages'][0]['text']})
    events('done',result)
    return result,evidence
