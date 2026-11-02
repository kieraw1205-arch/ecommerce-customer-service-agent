"""Validated calls to existing commerce endpoints. No automatic write retries."""
import os
import re
import httpx
from pydantic import ValidationError
from my_agent.contracts import Envelope, OrderStatus, UserOrders, Logistics, ShippingResult, RefundResult, ProductData, identifier

from my_agent.security import authorization_headers
from my_agent.telemetry import instrument, current_trace, record_error
from my_agent.audit import record_tool

BASE_URL = os.getenv('ECOMMERCE_API_BASE_URL', 'http://127.0.0.1:18081').rstrip('/')


class BusinessAPIError(ValueError):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


@instrument("api", "commerce_request")
def _request(method, path, schema, target_field, target, body=None, *, protocol=False, expected_request=None):
    write = method == 'POST'
    headers=authorization_headers()
    trace=current_trace()
    if trace:headers['X-Trace-ID']=trace.trace_id
    options={'headers':headers} if headers else {}
    try:
        if write:
            reply = httpx.post(f'{BASE_URL}{path}', json=body, timeout=10.0, **options)
        else:
            reply = httpx.get(f'{BASE_URL}{path}', timeout=10.0, **options)
        if protocol and reply.headers.get(protocol if isinstance(protocol,str) else 'X-Shipping-Protocol') != 'confirmed-idempotency-v1':
            raise BusinessAPIError('upgrade_required', '催发货服务版本尚未就绪，当前不会提交，请先升级业务服务。')
        reply.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        kind, message = {
            401: ('authentication', '身份认证失败，请重新登录。'),
            403: ('permission', '无权执行该操作。'),
            400: ('ineligible', '订单当前状态不允许催发货。'),
            404: ('not_found', '未找到对应用户、订单或物流信息。'),
            409: ('conflict', '已存在催发货申请或请求标识冲突，请勿重复提交。'),
            422: ('invalid_request', '请求参数未通过业务接口校验。'),
        }.get(status, ('outcome_unknown' if write else 'unavailable',
                       '提交结果待核实，请使用原请求标识重试。' if write else '业务服务暂时不可用，请稍后重试。'))
        record_error('authentication' if status==401 else 'permission' if status in {403,404} else 'internal')
        raise BusinessAPIError(kind, message) from None
    except httpx.RequestError:
        raise BusinessAPIError('outcome_unknown' if write else 'unavailable',
            '提交结果待核实，请使用原请求标识重试。' if write else '业务服务暂时不可用，请稍后重试。') from None
    try:
        envelope = Envelope.model_validate(reply.json())
        if envelope.code != 0:
            raise ValueError('business failure')
        data = schema.model_validate(envelope.data)
        if getattr(data, target_field) != target:
            raise ValueError('target mismatch')
        if (write and data.request_id != body['request_id']) or (expected_request and data.request_id != expected_request):
            raise ValueError('request mismatch')
        return data.model_dump(mode='json')
    except (ValueError, TypeError, ValidationError):
        raise BusinessAPIError('outcome_unknown' if write else 'invalid_response',
            '提交结果待核实，请使用原请求标识重试。' if write else '业务接口返回数据异常，暂时无法确认查询结果。') from None


def get_user_orders(user_id: str) -> dict:
    identifier(user_id)
    return _request('GET', f'/users/{user_id}/orders', UserOrders, 'user_id', user_id)


def get_order_status(order_id: str) -> dict:
    identifier(order_id)
    return _request('GET', f'/orders/{order_id}/status', OrderStatus, 'order_id', order_id)


def get_order_logistics(order_id: str) -> dict:
    identifier(order_id)
    return _request('GET', f'/orders/{order_id}/logistics', Logistics, 'order_id', order_id)


def get_shipping_reminder(order_id: str, request_id: str) -> dict | None:
    """Read the receipt; None means absent on a protocol-compatible server."""
    identifier(order_id)
    if not isinstance(request_id, str) or not re.fullmatch(r'U[0-9a-f]{32}', request_id):
        raise BusinessAPIError('invalid_request', '请求标识无效。')
    try:
        return _request('GET', f'/orders/{order_id}/shipping-reminders/{request_id}', ShippingResult,
                        'order_id', order_id, protocol=True, expected_request=request_id)
    except BusinessAPIError as exc:
        if exc.kind == 'not_found':
            return None
        raise


def create_shipping_reminder(order_id: str, request_id: str, *, confirmed: bool = False, expected_status: str | None = None) -> dict:
    identifier(order_id)
    if confirmed is not True:
        raise BusinessAPIError('confirmation_required', '催发货尚未获得用户明确确认。')
    if not isinstance(request_id, str) or not re.fullmatch(r'U[0-9a-f]{32}', request_id):
        raise BusinessAPIError('invalid_request', '请求标识无效。')
    if expected_status not in {'待发货', '待揽收'}:
        raise BusinessAPIError('invalid_request', '缺少有效的已确认订单状态。')
    existing = get_shipping_reminder(order_id, request_id)
    if existing is not None:
        return existing
    record_tool('create_shipping_reminder',{'order_id':order_id})
    return _request('POST', f'/orders/{order_id}/shipping-reminders', ShippingResult,
        'order_id', order_id, {'confirmed': True, 'request_id': request_id,
                             'submitted_by': 'customer-service-agent', 'note': '用户确认催发货', 'expected_status': expected_status})


def get_product(product_id: str) -> dict:
    identifier(product_id)
    return _request('GET', f'/products/{product_id}', ProductData, 'product_id', product_id)


def get_user_products(user_id: str) -> dict:
    identifier(user_id)
    # Reuse the existing sidebar API while validating owner echo and shape.
    class Products(Envelope):
        pass
    from pydantic import BaseModel
    class Data(BaseModel):
        user_id: str
        products: list[dict]
    return _request('GET', f'/users/{user_id}/products', Data, 'user_id', user_id)


def get_refund_application(order_id: str, request_id: str) -> dict | None:
    identifier(order_id)
    if not isinstance(request_id,str) or not re.fullmatch(r'R[0-9a-f]{32}',request_id):
        raise BusinessAPIError('invalid_request','请求标识无效。')
    try:
        return _request('GET',f'/orders/{order_id}/refund-applications/{request_id}',RefundResult,
                        'order_id',order_id,protocol='X-Refund-Protocol',expected_request=request_id)
    except BusinessAPIError as exc:
        if exc.kind=='not_found':return None
        raise


def create_refund_application(order_id: str, request_id: str, *, reason: str, expected_status: str, confirmed: bool=False) -> dict:
    identifier(order_id)
    if confirmed is not True:raise BusinessAPIError('confirmation_required','尚未获得明确退款确认。')
    if not isinstance(reason,str) or not 0<len(reason.strip())<=255 or not isinstance(expected_status,str) or not expected_status:
        raise BusinessAPIError('invalid_request','退款原因或订单状态无效。')
    existing=get_refund_application(order_id,request_id)
    if existing is not None:return existing
    record_tool('create_refund_application',{'order_id':order_id,'reason':reason.strip()})
    return _request('POST',f'/orders/{order_id}/refund-applications',RefundResult,'order_id',order_id,
        {'confirmed':True,'request_id':request_id,'expected_status':expected_status,
         'reason':reason.strip(),'submitted_by':'customer-service-agent'})
