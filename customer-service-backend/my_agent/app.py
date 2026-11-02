"""Minimal deployable Agent API; legacy Graph/Checkpointer remain unchanged."""
import asyncio,json,logging
from uuid import UUID,uuid4
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from my_agent.security import AuthMiddleware,current_principal
from my_agent.runtime import execute,history
from my_agent.api_client import get_user_orders,get_user_products,BusinessAPIError

_trace_logger=logging.getLogger('my_agent.telemetry')
_trace_logger.setLevel(logging.INFO)
if not _trace_logger.handlers:
    _handler=logging.StreamHandler()
    _handler.setFormatter(logging.Formatter('%(message)s'))
    _trace_logger.addHandler(_handler)
_trace_logger.propagate=False
app=FastAPI(title='电商小二 Agent',version='0.2.0')
app.add_middleware(AuthMiddleware,env_var='AGENT_AUTH_TOKENS_JSON')

class ChatRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=4000)
    conversation_id:UUID
    message_id:UUID=Field(default_factory=uuid4)

@app.get('/health')
def health():return {'status':'ok','agent':'langgraph','stream':'node-progress-and-final-reply'}

@app.get('/api/me')
def me():return {'user_id':current_principal().user_id}

def api_error(exc):
    code={'authentication':401,'permission':403,'not_found':404,'invalid_request':422}.get(exc.kind,503)
    raise HTTPException(status_code=code,detail=str(exc)) from None

@app.get('/api/orders')
def orders():
    try:return get_user_orders(current_principal().user_id)
    except BusinessAPIError as exc:api_error(exc)

@app.get('/api/products')
def products():
    try:return get_user_products(current_principal().user_id)
    except BusinessAPIError as exc:api_error(exc)

@app.get('/api/chat/history')
def chat_history(conversation_id:UUID):
    return {'conversation_id':str(conversation_id),'messages':history(conversation_id)}

@app.post('/api/chat')
async def chat(body:ChatRequest,request:Request):
    from fastapi.responses import JSONResponse
    trace_id=request.state.trace_id
    try:result,_=await asyncio.to_thread(execute,body.text,body.conversation_id,body.message_id,trace_id=trace_id)
    except ValueError:raise HTTPException(status_code=409,detail='消息标识已用于其他内容。') from None
    return JSONResponse(result,headers={'X-Trace-ID':trace_id})

@app.post('/api/chat/stream')
async def stream_chat(body:ChatRequest,request:Request):
    trace_id=request.state.trace_id;queue=asyncio.Queue();loop=asyncio.get_running_loop()
    def emit(kind,data):loop.call_soon_threadsafe(queue.put_nowait,(kind,data))
    def work():
        try:execute(body.text,body.conversation_id,body.message_id,trace_id=trace_id,emit=emit)
        except Exception:
            emit('error',{'kind':'execution_failed','message':'请求未完整完成，请保留消息标识核实结果。','trace_id':trace_id})
        finally:emit('_end',{})
    async def generate():
        task=asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:kind,data=await asyncio.wait_for(queue.get(),timeout=15)
                except asyncio.TimeoutError:
                    yield ': keep-alive\n\n';continue
                if kind=='_end':break
                yield 'event: '+kind+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
        finally:
            # Explicitly confirmed requests may already be committed. Finish and
            # checkpoint even if the HTTP client disconnects; never auto-resubmit.
            if not task.done():task.add_done_callback(lambda t:t.exception() if not t.cancelled() else None)
    return StreamingResponse(generate(),media_type='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','X-Trace-ID':trace_id})

# Static frontend is optional until its build gate passes. API stays authenticated.
import os
dist=os.getenv('AGENT_FRONTEND_DIST')
if dist and Path(dist).is_dir():
    app.mount('/demo',StaticFiles(directory=dist,html=True),name='demo')
