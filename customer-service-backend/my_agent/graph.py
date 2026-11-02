from my_agent.checkpoint import make_checkpointer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from my_agent.state import AgentState
from my_agent.routing import route_intent
from my_agent.nodes import (
    tools,
    call_model,
    recognize_intent_node,
    clarify_node,
    business_node,
    logistics_node,
    knowledge_node,
    chat_node,
    unsupported_node,
    cancel_node,
)

# 1. 创建状态图
builder = StateGraph(AgentState)

# 2. 注册节点
builder.add_node("intent", recognize_intent_node)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(tools))

builder.add_node("clarify", clarify_node)
builder.add_node("business", business_node)
builder.add_node("logistics", logistics_node)
builder.add_node("knowledge", knowledge_node)
builder.add_node("chat", chat_node)
builder.add_node("unsupported", unsupported_node)
builder.add_node("cancel", cancel_node)

# 3. 用户请求首先进入意图识别
builder.add_edge(START, "intent")

# 4. 按意图选择不同的处理节点
builder.add_conditional_edges(
    "intent",
    route_intent,
    {
        "query": "agent",
        "clarify": "clarify",
        "business": "business",
        "logistics": "logistics",
        "knowledge": "knowledge",
        "chat": "chat",
        "unsupported": "unsupported",
        "cancel": "cancel",
    },
)

# 5. 保留原有订单工具调用循环
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")

# 6. 其他分支完成后结束
for node in [
    "clarify",
    "business",
    "logistics",
    "knowledge",
    "chat",
    "unsupported",
    "cancel",
]:
    builder.add_edge(node, END)


# 7. 编译
memory = make_checkpointer()
graph = builder.compile(checkpointer=memory)