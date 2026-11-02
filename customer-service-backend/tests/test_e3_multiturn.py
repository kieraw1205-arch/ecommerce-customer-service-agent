"""E3-07：完整 Graph 多轮状态回归。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from my_agent.graph import graph


ORDER_ID = "A20260410001"


def intent_result(intent, order_id=None, user_id=None, sub_intents=None):
    """生成与 IntentResult 接口兼容的模拟结果。"""
    from my_agent.intent import IntentResult

    return IntentResult(
        intent=intent,
        order_id=order_id,
        user_id=user_id,
        reason="mock_test",
        sub_intents=sub_intents or [],
    )


class TestMultiTurn(unittest.TestCase):

    def invoke(self, thread_id, message):
        return graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            {"configurable": {"thread_id": thread_id}},
        )

    @patch("my_agent.nodes.recognize_intent")
    def test_workflow_resume_cancel(self, mock_intent):
        from my_agent.intent import SubIntent

        mock_intent.return_value = intent_result(
            "multi_intent",
            order_id=ORDER_ID,
            sub_intents=[
                SubIntent(
                    intent="order_status",
                    order_id=ORDER_ID,
                ),
                SubIntent(
                    intent="shipping_reminder",
                    order_id=ORDER_ID,
                    condition="订单未发货",
                ),
            ],
        )

        thread = "e3-multiturn-resume-cancel"

        r1 = self.invoke(
            thread,
            f"查询订单 {ORDER_ID}，如果没发货就催一下",
        )
        self.assertIsNotNone(r1.get("pending_workflow"))

        r2 = self.invoke(thread, "那接下来呢？")
        self.assertIsNotNone(r2.get("pending_workflow"))
        self.assertEqual(
            r2["pending_workflow"]["current_step"], 0
        )

        mock_intent.return_value = intent_result("cancel")

        r3 = self.invoke(thread, "算了，不用了")
        self.assertIsNone(r3.get("pending_workflow"))

        r4 = self.invoke(thread, "继续")
        self.assertIsNone(r4.get("pending_workflow"))

    @patch("my_agent.nodes.recognize_intent")
    def test_switch_to_new_task(self, mock_intent):
        from my_agent.intent import SubIntent

        mock_intent.side_effect = [
            intent_result(
                "multi_intent",
                order_id=ORDER_ID,
                sub_intents=[
                    SubIntent(intent="order_status", order_id=ORDER_ID),
                    SubIntent(
                        intent="shipping_reminder",
                        order_id=ORDER_ID,
                        condition="订单未发货",
                    ),
                ],
            ),
            intent_result("order_status"),
        ]

        thread = "e3-multiturn-switch"

        r1 = self.invoke(
            thread,
            f"查询订单 {ORDER_ID}，如果没发货就催一下",
        )
        self.assertIsNotNone(r1.get("pending_workflow"))

        r2 = self.invoke(
            thread,
            "先帮我查一下别的订单状态",
        )

        self.assertEqual(
            r2["intent_result"]["intent"],
            "order_status",
        )
        self.assertIsNone(r2.get("pending_workflow"))
        self.assertIsNotNone(r2.get("pending_intent"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
