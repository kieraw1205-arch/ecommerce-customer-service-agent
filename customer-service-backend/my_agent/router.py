from fastapi import APIRouter, HTTPException
import httpx

from my_agent.api_client import get_user_orders, BusinessAPIError
from my_agent.security import current_principal

router = APIRouter(prefix="/my-agent", tags=["My Agent"])


@router.get("/users/{user_id}/orders")
def query_user_orders(user_id: str):
    """通过客服后端查询电商订单。"""

    if user_id != current_principal().user_id:
        raise HTTPException(status_code=404, detail="资源不存在。")
    try:
        return get_user_orders(user_id)
    except BusinessAPIError as exc:
        raise HTTPException(status_code={"authentication":401,"permission":403,"not_found":404}.get(exc.kind,503),detail=str(exc)) from None

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="用户不存在"
            ) from exc

        raise HTTPException(
            status_code=502,
            detail="电商业务服务返回错误"
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="电商业务服务暂时不可用"
        ) from exc