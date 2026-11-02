from langgraph.graph import MessagesState


class AgentState(MessagesState):
    intent_result: dict | None
    pending_intent: dict | None
    pending_workflow: dict | None
    shipping_workflow: dict | None

    refund_workflow: dict | None
    request_receipts: dict | None
