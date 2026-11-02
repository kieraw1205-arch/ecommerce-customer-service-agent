"""Read tools exposed to Qwen; writes remain inside the confirmation workflow."""
from langchain_core.tools import tool
from my_agent.api_client import get_user_orders, get_order_status, get_order_logistics, BusinessAPIError, get_product


from my_agent.telemetry import instrument
from my_agent.audit import record_tool

def _safe(function, target):
    names={'get_user_orders':('query_user_orders','user_id'),'get_order_status':('query_order_status','order_id'),
           'get_order_logistics':('query_order_logistics','order_id'),'get_product':('query_product','product_id')}
    name,key=names[function.__name__]
    record_tool(name,{key:target})
    try:
        return {'ok': True, 'data': function(target)}
    except BusinessAPIError as exc:
        return {'ok': False, 'error': {'kind': exc.kind, 'message': str(exc)}}
    except ValueError:
        return {'ok': False, 'error': {'kind': 'invalid_request', 'message': '用户 ID 或订单号格式无效。'}}


@tool
@instrument("tool", "query_user_orders")
def query_user_orders(user_id: str) -> dict:
    """查询指定用户最近的最多 5 笔订单，需要用户 ID。"""
    return _safe(get_user_orders, user_id)


@tool
@instrument("tool", "query_order_status")
def query_order_status(order_id: str) -> dict:
    """查询指定订单当前状态及状态说明，需要订单号。"""
    return _safe(get_order_status, order_id)


@tool
@instrument("tool", "query_order_logistics")
def query_order_logistics(order_id: str) -> dict:
    """只读查询指定订单的物流公司、运单号和真实物流轨迹。"""
    return _safe(get_order_logistics, order_id)


@tool
@instrument("tool", "query_product")
def query_product(product_id: str) -> dict:
    """只读查询现有商品详情与规格，不生成未知政策。"""
    return _safe(get_product,product_id)
