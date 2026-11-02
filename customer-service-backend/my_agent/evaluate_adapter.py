"""Intent-only live adapter; the private MySQL task adapter is excluded. Expected labels are never passed to this module."""

def messages(history):
    from langchain_core.messages import HumanMessage,AIMessage
    return [(HumanMessage if m['role'] in {'human','user'} else AIMessage)(content=m['content']) for m in history]

def predict_intent(payload):
    from my_agent.intent import recognize_intent
    from my_agent.telemetry import trace_scope
    context=messages(payload.get('history',[]))
    from langchain_core.messages import HumanMessage
    context += [HumanMessage(content=t) for t in payload.get('prior_turns',[])]
    with trace_scope() as trace:
        intent=recognize_intent(payload['message'],context).model_dump(mode='json')
    summary=trace.summary();tokens=summary['tokens']
    return {**intent,'capabilities':['intent'],'trace_id':trace.trace_id,'latency_ms':summary['duration_ms'],
            'tokens':{'input':tokens['input_tokens'],'output':tokens['output_tokens'],'total':tokens['total_tokens']}}
