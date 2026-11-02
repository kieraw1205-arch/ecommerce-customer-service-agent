
"""Agent 任务状态转换规则。"""

INDEPENDENT_INTENTS = {
    "order_list",
    "order_status",
    "logistics",
    "shipping_reminder",
    "refund",
    "product_qa",
    "unsupported",
}



def get_task_state_updates(
    intent_data: dict,
    branch: str,
    workflow: dict | None,
    *,
    independent_request: bool = False,
) -> dict:
    """根据新请求与已有工作流的关系，更新任务状态。"""

    intent = intent_data.get("intent")
    updates = {}

    # 1. 用户取消：清理所有待办
    if intent == "cancel":
        return {
            "pending_intent": None,
            "pending_workflow": None,
        }

    # 2. 独立的新任务会替代旧工作流
    # 即使新任务缺少订单号，也必须清除旧计划
    if (
        workflow is not None
        and independent_request
        and intent in INDEPENDENT_INTENTS
    ):
        updates["pending_workflow"] = None

    # 3. 需要澄清时，保留新任务的待办状态
    # clarify_node 负责写入新的 pending_intent
    if branch == "clarify":
        return updates

    # 4. 不需要澄清时，清理旧参数待办
    updates["pending_intent"] = None

    return updates
