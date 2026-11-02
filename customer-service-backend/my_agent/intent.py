
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    BaseMessage,
)
from my_agent.llm import llm
from my_agent.telemetry import TelemetryCallback

# 子任务
class SubIntent(BaseModel):
    intent: Literal[
        "order_list",
        "order_status",
        "logistics",
        "shipping_reminder",
        "refund",
        "product_qa",
        "chitchat",
        "unsupported",
    ] = Field(description="子任务的具体意图")

    order_id: str | None = Field(
        default=None,
        description="子任务涉及的订单号",
    )

    condition: str | None = Field(
        default=None,
        description="执行该任务需要满足的条件，没有条件则为None",
    )

# 1. 定义意图识别结果的数据结构
class IntentResult(BaseModel):
    intent: Literal[
        "order_list",
        "order_status",
        "logistics",
        "shipping_reminder",
        "refund",
        "product_qa",
        "chitchat",
        "multi_intent",
        "unclear",
        "unsupported",
        "cancel",
    ] = Field(description="用户意图类别")

    user_id: str | None = Field(
        default=None,
        description="用户明确提供的用户ID",
    )

    order_id: str | None = Field(
        default=None,
        description="用户明确提供的订单号",
    )

    product_id: str | None = Field(default=None, description="用户明确提供的商品SKU编号")
    refund_reason: str | None = Field(default=None, description="用户明确表达的退款原因；不提供则None，不得使用分类原因代替")

    reason: str = Field(description="识别原因")

    sub_intents: list[SubIntent] = Field(
    default_factory=list,
    description="复合意图包含的子任务，按用户表达的执行顺序排列",
)
    @field_validator("user_id", "order_id", "product_id", "refund_reason", mode="before")
    @classmethod
    def normalize_empty_id(cls, value):
        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()

            if value.lower() in {"", "none", "null"}:
                return None

        return value

# 2. 让 Qwen 按指定结构输出
intent_llm = llm.with_structured_output(
    IntentResult,
    method="function_calling",
)


# 3. 定义意图识别函数
def recognize_intent(
    user_message: str,
    history: list[BaseMessage] | None = None,
) -> IntentResult:

    messages = [
        SystemMessage(
            content="""
        你是电商客服意图识别器。
        你的任务是识别用户真正想完成的事情，并提取参数。
        只负责分类，不执行业务操作。

        意图分类规则：

        1. order_list：查询某个用户有哪些订单。
        例如：查询 u1001 的订单、查看我的全部订单。

        2. order_status：查询某一笔订单的状态。
        例如：订单 A20260410001 是否发货、这单是什么状态。

        3. logistics：查询物流、快递位置、物流进度。
        例如：我的快递到哪里了、查看物流信息。

        4. shipping_reminder：明确要求催促商家发货。
        例如：帮我催发货、催一下卖家。

        5. refund：明确申请退款、退货或取消订单。
        例如：我要退款、帮我申请退货。

        6. product_qa：咨询商品信息、购买规则或售后政策。
        例如：支持七天无理由退货吗？
        例如：退款需要多久、这个商品有什么功能？

        7. chitchat：问候、闲聊。

        8. multi_intent：同时提出多个独立业务需求。

        9. unclear：用户表达模糊，无法确定具体需求。

        10. unsupported：请求超出电商客服业务范围。

        11.cancel：用户明确表示取消、停止或放弃当前任务。
        例如：算了，不查了；不用继续了；取消刚才的请求。

        注意：
        - 取消当前客服任务，不等于取消电商订单。
        - 如果用户要求取消真实订单，应识别为相应业务操作，
        不能直接清除会话状态并声称订单已取消。

        商品与退款槽位规则：
        - SKU_TEST_001 等商品编号写入 product_id，商品规格或售后咨询归 product_qa。
        - 用户明确给出的退款原因写入 refund_reason；没有给出时保持 None。
        - reason 是分类解释，绝对不能当作退款原因。
        - 最新消息中的明确订单号优先，不能用历史订单号覆盖。

        重要区分规则：
        - 查询订单列表，不等于查询单笔订单状态。
        - 询问退款、退货政策，不等于申请退款。
        - 询问发货状态，不等于要求催发货。
        - 只有用户明确表达操作意愿，才识别为操作类意图。
        - 如果同时提出多个独立需求，使用 multi_intent。
        - 未提供用户ID或订单号时，字段保持 None。
        - 不得编造订单号或用户ID。

        复合意图识别规则：
        1. 用户提出两个或以上独立任务时，intent 使用 multi_intent。
        2. 将各任务按执行顺序放入 sub_intents。
        3. 如果后续任务有条件，将条件写入 condition。
        4. 不得自行认定条件已经满足。
        5. 只负责识别，不执行任何业务操作。
        6. 单一意图时，sub_intents 返回空列表。
        """
        ),
    ]
    if history:
        messages.extend(history)

    messages.append(HumanMessage(content=user_message))

    return intent_llm.invoke(messages, config={"callbacks": [TelemetryCallback()]})
