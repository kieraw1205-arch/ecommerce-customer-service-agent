
from my_agent.state import AgentState


def route_intent(state: AgentState) -> str:
    """根据识别结果，决定进入哪个处理分支。"""

    result = state.get("intent_result") or {}
    intent = result.get("intent")

    # 1. 查询类请求：先检查参数
    if intent == "order_list":
        if not result.get("user_id"):
            return "clarify"
        return "query"

    if intent == "order_status":
        if not result.get("order_id"):
            return "clarify"
        return "query"

    # 2. 物流查询
    if intent == "logistics":
        if not result.get("order_id"):
            return "clarify"
        return "logistics"

    # 3. 业务操作及复合任务
    if intent in {
        "shipping_reminder",
        "refund",
        "multi_intent",
    }:
        return "business"

    # 4. 知识问答
    if intent == "product_qa":
        return "knowledge"

    # 5. 闲聊
    if intent == "chitchat":
        return "chat"

    # 6. 模糊或不支持的请求
    if intent == "unclear":
        return "clarify"


    if intent == "cancel":

         return "cancel"

    return "unsupported"
