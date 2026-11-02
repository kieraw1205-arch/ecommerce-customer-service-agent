"""Small bearer-auth boundary; identity comes from server configuration only."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json, os, re, secrets, logging, time
from uuid import UUID, uuid4
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

@dataclass(frozen=True)
class Principal:
    user_id: str
    token: str = field(repr=False)

_identity: ContextVar[Principal | None] = ContextVar('commerce_identity',default=None)

def current_principal():
    value=_identity.get()
    if value is None:raise HTTPException(status_code=401,detail='需要身份认证。')
    return value

@contextmanager
def identity_scope(user_id, token):
    marker=_identity.set(Principal(user_id,token))
    try:yield _identity.get()
    finally:_identity.reset(marker)

def authorization_headers():
    principal=_identity.get()
    return {'Authorization':'Bearer '+principal.token} if principal else {}

def authenticate(authorization, env_var):
    value=os.getenv(env_var) or os.getenv('AUTH_TOKENS_JSON','')
    try:
        mapping=json.loads(value)
        if not isinstance(mapping,dict) or not mapping:raise ValueError()
        if any(not isinstance(k,str) or not k or not isinstance(v,str) or
               not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',v) for k,v in mapping.items()):raise ValueError()
    except (ValueError,TypeError):
        raise HTTPException(status_code=503,detail='认证服务尚未配置。') from None
    if not isinstance(authorization,str) or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401,detail='需要有效的访问令牌。')
    token=authorization[7:]
    for configured,user_id in mapping.items():
        if secrets.compare_digest(token.encode(),configured.encode()):return Principal(user_id,token)
    raise HTTPException(status_code=401,detail='需要有效的访问令牌。')

class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self,app,env_var='AUTH_TOKENS_JSON'):
        super().__init__(app);self.env_var=env_var

    async def dispatch(self,request,call_next):
        try:trace_id=UUID(request.headers.get('X-Trace-ID','')).hex
        except (ValueError,TypeError,AttributeError):trace_id=uuid4().hex
        request.state.trace_id=trace_id
        started=time.monotonic()
        response=await self._authenticated(request,call_next)
        response.headers['X-Trace-ID']=response.headers.get('X-Trace-ID',trace_id)
        route=getattr(request.scope.get('route'),'path','unmatched')
        logger=logging.getLogger('ecommerce.requests')
        logger.info(json.dumps({'event':'http_request','trace_id':response.headers['X-Trace-ID'],
            'route':route,'method':request.method,'status':response.status_code,
            'duration_ms':round((time.monotonic()-started)*1000,3),
            'error_type':{401:'authentication',403:'permission',404:'not_found',422:'validation',503:'unavailable'}.get(response.status_code)}))
        return response

    async def _authenticated(self,request,call_next):
        if request.url.path.startswith('/demo/') or request.url.path=='/demo' or request.url.path in {'/health','/docs','/openapi.json','/docs/oauth2-redirect'}:
            return await call_next(request)
        try:principal=authenticate(request.headers.get('authorization'),self.env_var)
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail},status_code=exc.status_code,
                                headers={'WWW-Authenticate':'Bearer'} if exc.status_code==401 else None)
        with identity_scope(principal.user_id,principal.token):
            request.state.principal=principal
            return await call_next(request)

_request_logger=logging.getLogger('ecommerce.requests')
_request_logger.setLevel(logging.INFO)
if not _request_logger.handlers:
    _request_handler=logging.StreamHandler()
    _request_handler.setFormatter(logging.Formatter('%(message)s'))
    _request_logger.addHandler(_request_handler)
_request_logger.propagate=False
