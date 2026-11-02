"""Request-local execution evidence, never written to logs."""
from contextlib import contextmanager
from contextvars import ContextVar
_calls=ContextVar('agent_tool_calls',default=None)
@contextmanager
def capture_calls():
    value=[];marker=_calls.set(value)
    try:yield value
    finally:_calls.reset(marker)
def record_tool(name,args):
    value=_calls.get()
    if value is not None:value.append({'name':name,'args':dict(args)})
