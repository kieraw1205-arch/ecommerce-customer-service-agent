
import re
from my_agent.workflow_validation import validate_pending_workflow

from langchain_core.messages import HumanMessage, AIMessage
from my_agent.task_transition import get_task_state_updates
from my_agent.state import AgentState
from my_agent.llm import llm
from my_agent.prompts import SYSTEM_MESSAGE
from my_agent.intent import recognize_intent
from my_agent.routing import route_intent
from my_agent.tools import query_user_orders, query_order_status, query_order_logistics, query_product
from my_agent.query_flow import query_turn, render
from my_agent.shipping_workflow import control_intent, handle_business


# =========================
# 1. Agent 工具配置
# =========================

tools = [query_user_orders, query_order_status, query_order_logistics, query_product]

llm_with_tools = llm.bind_tools(tools)


# =========================
# 2. LLM 节点
# =========================

def call_model(state: AgentState) -> dict:
    """Retain Qwen Tool Calling and the Graph tool loop, constrain the target."""
    return query_turn(state, llm_with_tools, SYSTEM_MESSAGE)


# =========================
# 3. 待办任务辅助判断
# =========================

def is_pending_help_request(
    message: str,
    pending: dict | None,
) -> bool:
    """判断用户是否在询问如何补充当前任务所需的信息。"""

    if not pending:
        return False

    if pending.get("intent") not in {"order_status", "logistics"}:
        return False

    text = message.strip()

    help_expressions = [
        "不知道订单号",
        "找不到订单号",
        "订单号在哪里",
        "订单号在哪",
        "怎么找订单号",
        "没有订单号",
    ]

    return any(
        expression in text
        for expression in help_expressions
    )


# =========================
# 4. 意图识别节点
# =========================
def is_workflow_resume_request(
    message: str,
    workflow: dict | None,
) -> bool:
    """判断用户是否希望继续尚未完成的复合任务。"""

    if not workflow:
        return False

    if workflow.get("status") != "pending":
        return False

    text = message.strip()

    resume_expressions = [
        "那接下来呢",
        "接下来呢",
        "然后呢",
        "继续",
        "继续处理",
        "按刚才的来",
        "接着处理",
    ]

    return any(
        expression in text
        for expression in resume_expressions
    )

def _recognize_intent_e3(state: AgentState) -> dict:
    """识别最新用户意图，并更新共享状态。"""

    messages = state["messages"]

    # 4.1 找到最新一条用户消息
    current_index = next(
        i for i in range(len(messages) - 1, -1, -1)
        if isinstance(messages[i], HumanMessage)
    )

    current_message = messages[current_index].content

    # 4.2 读取之前未完成的任务
    pending = state.get("pending_intent")

    workflow = state.get("pending_workflow")

    # 用户明确要求继续，但当前没有可恢复的工作流
    resume_expressions = {
        "继续",
        "继续吧",
        "继续处理",
        "接着处理",
        "然后呢",
        "那接下来呢",
        "那接下来呢？",
        "按刚才的来",
    }

    if current_message.strip() in resume_expressions and not workflow:
        return {
            "intent_result": {
                "intent": "unclear",
                "user_id": None,
                "order_id": None,
                "reason": "用户要求继续，但当前没有可恢复的工作流",
                "sub_intents": [],
            },
            "pending_intent": None,
            "pending_workflow": None,
        }

    # 存在工作流时，继续此前保存的计划
    if is_workflow_resume_request(current_message, workflow):
        valid, error = validate_pending_workflow(workflow)

        if not valid:
            return {
                "intent_result": {
                    "intent": "unclear",
                    "user_id": None,
                    "order_id": None,
                    "reason": f"invalid_workflow: {error}",
                    "sub_intents": [],
                },
                "pending_workflow": None,
                "pending_intent": None,
            }

        return {
            "intent_result": {
                "intent": "multi_intent",
                "user_id": None,
                "order_id": None,
                "reason": "用户希望继续之前保存的复合任务",
                "sub_intents": [
                    {
                        "intent": task["intent"],
                        "order_id": task.get("order_id"),
                        "condition": task.get("condition"),
                    }
                    for task in workflow["tasks"]
                ],
            },
            "pending_workflow": workflow,
        }
    # 4.3 【本次修复】
    # 用户不知道订单号在哪里找时，保留原任务
    if is_pending_help_request(current_message, pending):
        return {
            "intent_result": {
                **pending,
                "needs_help": True,
            }
        }

    # 4.4 用户直接补充订单号时，恢复原查询任务
    order_match = re.fullmatch(
        r"[A-Z]\d{11}",
        current_message.strip().upper(),
    )

    if (
        pending
        and pending.get("intent") == "order_status"
        and order_match
    ):
        intent_data = {
            **pending,
            "order_id": order_match.group(),
            "reason": "用户补充订单号，恢复之前的订单状态查询",
        }

        return {
            "intent_result": intent_data,
            "pending_intent": None,
        }

    # 4.5 提取历史对话
    history = [
        msg
        for msg in messages[:current_index]
        if isinstance(msg, HumanMessage)
        or (
            isinstance(msg, AIMessage)
            and not msg.tool_calls
        )
    ]

    # 4.6 调用 Qwen 识别意图
    try:
        result = recognize_intent(
            user_message=current_message,
            history=history,
        )

        intent_data = result.model_dump()

        if not intent_data.get("intent"):
            raise ValueError("意图识别结果缺少 intent")

    except Exception:
        return {
            "intent_result": {
                "intent": "unclear",
                "user_id": None,
                "order_id": None,
                "reason": "intent_recognition_failed",
                "sub_intents": [],
            },

        }

    # 4.7 判断当前请求进入哪个分支
    branch = route_intent({
        "intent_result": intent_data
    })

    # 读取当前复合工作流
    workflow = state.get("pending_workflow")

    # 当前先识别具有明确业务参数的独立请求
    # 例如：帮我查询用户 u1002 的订单
    has_explicit_target = (
        intent_data.get("user_id") is not None
        or intent_data.get("order_id") is not None
    )

    # 判断是否是明确的独立新请求
    explicit_new_task = any(
        phrase in current_message
        for phrase in [
            "别的订单",
            "另一个订单",
            "另一笔订单",
            "换个订单",
            "重新查",
            "另外帮我",
        ]
    )

    independent_request = (
        intent_data.get("intent") in {
            "order_list",
            "order_status",
            "logistics",
            "shipping_reminder",
            "refund",
        }
        and (
            has_explicit_target
            or explicit_new_task
        )
    )

    updates = {"intent_result": intent_data}

    updates.update(
        get_task_state_updates(
            intent_data=intent_data,
            branch=branch,
            workflow=workflow,
            independent_request=independent_request,
        )
    )

    return updates


# =========================
# 5. 澄清节点
# =========================

def clarify_node(state: AgentState) -> dict:
    """必要信息缺失时向用户澄清。"""

    result = state["intent_result"]
    intent = result["intent"]
    # 意图识别失败时，直接回复错误提示
    # 不覆盖原来的待办任务
    if result.get("reason") == "intent_recognition_failed":
        return {
            "messages": [
                AIMessage(
                    content="抱歉，当前服务暂时出现问题，请稍后重试刚才的请求。"
                )
            ]
        }

    # 用户不知道订单号在哪里找
    if result.get("needs_help"):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "您可以打开购物平台的“我的订单”，"
                        "找到对应商品，进入订单详情页面查看订单号。"
                        "找到后发给我，我就可以继续帮您查询订单状态。"
                    )
                )
            ],
            "pending_intent": state.get("pending_intent"),
        }
    if result.get("reason") == "用户要求继续，但当前没有可恢复的工作流":
        return {
            "messages": [
                AIMessage(
                    content=(
                        "当前没有可以继续的待办任务。"
                        "如果您希望重新查询订单或申请催发货，"
                        "请重新告诉我您的需求。"
                    )
                )
            ],
            "pending_intent": None,
            "pending_workflow": None,
        }


    if intent == "order_list":
        text = "请提供您的用户 ID，以便查询订单列表。"

    elif intent in {"order_status", "logistics"}:
        text = "请提供您要查询的订单号。"

    else:
        text = "请具体说明您希望我帮您处理什么问题。"

    return {
        "messages": [AIMessage(content=text)],
        "pending_intent": result,
    }


# =========================
# 6. 业务操作入口
# =========================

# def business_node(state: AgentState) -> dict:
    """业务入口：目前不执行写操作。"""

    result = state["intent_result"]
    intent = result["intent"]

    if intent == "multi_intent":
        tasks = [
            item["intent"]
            for item in result.get("sub_intents", [])
        ]
        text = f"已识别多个业务需求：{tasks}。当前尚未执行操作。"

    else:
        text = f"已识别业务需求：{intent}。当前尚未提交业务申请。"

    return {
        "messages": [AIMessage(content=text)]
    }

def _business_node_e3(state: AgentState) -> dict:
    """业务入口：保存复合任务，暂不执行写操作。"""

    result = state["intent_result"]
    intent = result["intent"]

    if intent == "multi_intent":
        if result.get("reason") == "用户希望继续之前保存的复合任务":
            workflow = state.get("pending_workflow")

            valid, error = validate_pending_workflow(workflow)

            if not valid:
                return {
                    "messages": [
                        AIMessage(
                            content=(
                                "之前保存的任务计划无法安全恢复："
                                f"{error}。请重新提出您的需求。"
                            )
                        )
                    ],
                    "pending_workflow": None,
                }

            tasks = workflow["tasks"]
            current_step = workflow["current_step"]
            current_task = tasks[current_step]

            return {
                "messages": [
                    AIMessage(
                        content=(
                            f"我们继续之前的任务计划。目前已保存 {len(tasks)} 个子任务，"
                            f"下一步是第 {current_step + 1} 项："
                            f"{current_task['intent']}。"
                            "目前仅恢复任务计划，尚未执行实际业务操作。"
                        )
                    )
                ]
            }

        # 1. 从意图识别结果中获取子任务
        sub_intents = result.get("sub_intents", [])

        # 2. 为每个子任务增加执行状态
        tasks = [
            {
                **item,
                "status": "pending",
            }
            for item in sub_intents
        ]

        # 3. 保存整个业务工作流
        workflow = {
            "status": "pending",
            "current_step": 0,
            "tasks": tasks,
        }

        # 4. 返回状态更新
        return {
            "pending_workflow": workflow,
            "messages": [
                AIMessage(
                    content=(
                        f"已识别 {len(tasks)} 个业务任务，"
                        "任务计划已保存，但尚未执行。"
                    )
                )
            ],
        }

    # 单一业务操作暂不执行
    return {
        "messages": [
            AIMessage(
                content=(
                    f"已识别业务需求：{intent}。"
                    "当前尚未提交业务申请。"
                )
            )
        ]
    }


# =========================
# 7. 物流节点
# =========================

def logistics_node(state: AgentState) -> dict:
    """Execute the existing read-only logistics API through a tool."""
    result = query_order_logistics.invoke({"order_id": state["intent_result"]["order_id"]})
    return {"messages": [AIMessage(content=render(result, "logistics"))]}


# =========================
# 8. 知识问答节点
# =========================

def knowledge_node(state: AgentState) -> dict:
    from my_agent.product_knowledge import answer
    return answer(state)


# =========================
# 9. 闲聊节点
# =========================

def chat_node(state: AgentState) -> dict:
    """处理简单问候。"""

    return {
        "messages": [
            AIMessage(
                content="您好！我是电商智能客服，请问有什么可以帮您？"
            )
        ]
    }


# =========================
# 10. 不支持的请求
# =========================

def unsupported_node(state: AgentState) -> dict:
    """处理当前不支持的请求。"""

    return {
        "messages": [
            AIMessage(
                content="抱歉，当前无法处理这类请求。"
            )
        ]
    }


# =========================
# 11. 任务取消节点
# =========================

# def cancel_node(state: AgentState) -> dict:
    """取消当前待办任务，不修改真实订单。"""

    return {
        "messages": [
            AIMessage(
                content="好的，已停止当前查询。如有其他需要，随时告诉我。"
            )
        ],
        "pending_intent": None,
    }


def cancel_node(state: AgentState) -> dict:
    """取消当前客服任务，不修改真实订单。"""

    return {
        "messages": [
            AIMessage(
                content="好的，已停止当前任务。如有其他需要，随时告诉我。"
            )
        ],
        "pending_intent": None,
        "pending_workflow": None,
    }

def recognize_intent_node(state: AgentState) -> dict:
    """Add deterministic authorization controls without replacing E3 recognition."""
    from my_agent.refund_workflow import control_intent as refund_controls
    controls = refund_controls(state) or control_intent(state)
    if controls and (controls.get("intent_result") or {}).get("intent")=="cancel":
        controls["refund_workflow"]=None
    pending=state.get("pending_intent") or {}
    text=next((m.content.strip() for m in reversed(state.get("messages",[])) if isinstance(m,HumanMessage) and isinstance(m.content,str)),"")
    if pending.get("intent")=="product_qa" and re.fullmatch(r"SKU[A-Za-z0-9_-]{1,60}",text):
        return {"intent_result":{"intent":"product_qa","product_id":text},"pending_intent":None}
    if controls is not None:
        return controls
    updates = _recognize_intent_e3(state)
    result = updates.get("intent_result") or {}
    ids=re.findall(r"\b[A-Z]\d{11}\b",text.upper())
    if (any(phrase in text for phrase in ["另外帮我","另一笔","另一个订单","换个订单","重新查"])
        and len(set(ids))==1 and any(word in text for word in ["状态","发货了吗","是否发货"])
        and not any(word in text for word in ["催","退款","物流","如果","不要","不查","别查"])):
        result={"intent":"order_status","order_id":ids[0],"user_id":None,"product_id":None,
                "refund_reason":None,"reason":"explicit_new_status_query","sub_intents":[]}
        updates["intent_result"]=result
        updates["pending_workflow"]=None
        updates["pending_intent"]=None
    intent = result.get("intent")
    previous = state.get("shipping_workflow")
    if intent in {"cancel","order_list","order_status","logistics","product_qa","shipping_reminder","unsupported"}:
        updates["refund_workflow"]=None
    if intent=="multi_intent" and result.get("reason")!="用户希望继续之前保存的复合任务":
        updates["refund_workflow"]=None
    if intent=="refund":
        old=state.get("refund_workflow")
        if isinstance(old,dict) and result.get("order_id")!=old.get("order_id"):
            updates["refund_workflow"]=None
    if intent=="order_list" and not result.get("user_id"):
        from my_agent.security import current_principal
        try:result["user_id"]=current_principal().user_id
        except Exception:pass
        updates["intent_result"]=result
    if intent == "cancel":
        updates["shipping_workflow"] = None
    elif intent in {"order_list", "order_status", "logistics", "refund", "unsupported"}:
        updates["shipping_workflow"] = None
    elif intent == "shipping_reminder" and isinstance(previous, dict) and result.get("order_id") != previous.get("order_id"):
        updates["shipping_workflow"] = None
    elif intent == "multi_intent" and result.get("reason") != "用户希望继续之前保存的复合任务":
        updates["shipping_workflow"] = None
    return updates


def business_node(state: AgentState) -> dict:
    """Preserve E3 planning state and add the E4 execution state separately."""
    if (state.get("intent_result") or {}).get("intent")=="refund":
        from my_agent.refund_workflow import handle
        return handle(state)
    legacy=_business_node_e3(state)
    if (state.get("intent_result") or {}).get("intent")=="multi_intent":
        from my_agent.multi_read import handle as multi_read
        outcome=multi_read(state)
        if outcome is not None:return {**legacy,**outcome}
    return handle_business(state,legacy)


# Keep the Graph registrations and persistence intact; observe node boundaries.
from my_agent.telemetry import instrument as _observe_node
for _name in ["recognize_intent_node","call_model","clarify_node","business_node","logistics_node",
              "knowledge_node","chat_node","unsupported_node","cancel_node"]:
    globals()[_name]=_observe_node("node",_name)(globals()[_name])
