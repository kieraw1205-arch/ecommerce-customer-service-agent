"""E3-07：真实 Graph 多轮状态恢复测试，Mock Qwen 意图识别。"""

import unittest
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import HumanMessage
from my_agent.graph import graph
from my_agent.intent import IntentResult, SubIntent


class TestStateRecovery(unittest.TestCase):

    def invoke(self, config, text):
        return graph.invoke(
            {"messages": [HumanMessage(content=text)]},
            config,
        )

    @patch("my_agent.nodes.recognize_intent")
    def test_workflow_survives_timeout_and_resumes(self, mock_intent):
        config = {
            "configurable": {
                "thread_id": f"e3-recovery-{uuid4().hex}"
            }
        }

        mock_intent.return_value = IntentResult(
            intent="multi_intent",
            order_id="A20260410001",
            reason="测试复合任务",
            sub_intents=[
                SubIntent(
                    intent="order_status",
                    order_id="A20260410001",
                ),
                SubIntent(
                    intent="shipping_reminder",
                    order_id="A20260410001",
                    condition="订单未发货",
                ),
            ],
        )

        # 第一轮：建立工作流
        r1 = self.invoke(
            config,
            "查询订单 A20260410001，如果没发货就催一下",
        )
        original = r1["pending_workflow"]
        self.assertEqual(len(original["tasks"]), 2)

        # 第二轮：模拟 Qwen 超时
        mock_intent.side_effect = TimeoutError("Qwen timeout")

        r2 = self.invoke(config, "我想换个问题")

        self.assertEqual(
            r2["intent_result"]["reason"],
            "intent_recognition_failed",
        )
        self.assertEqual(r2["pending_workflow"], original)
        self.assertIn("稍后重试", r2["messages"][-1].content)

        # 第三轮：恢复已有工作流，不重新调用 Qwen
        r3 = self.invoke(config, "那接下来呢？")

        self.assertEqual(
            r3["intent_result"]["intent"],
            "multi_intent",
        )
        self.assertEqual(r3["pending_workflow"], original)
        self.assertEqual(r3["pending_workflow"]["current_step"], 0)
        self.assertIn("继续之前的任务计划", r3["messages"][-1].content)

        self.assertEqual(mock_intent.call_count, 2)

    @patch("my_agent.nodes.recognize_intent")
    def test_pending_slot_survives_timeout(self, mock_intent):
        config = {
            "configurable": {
                "thread_id": f"e3-pending-{uuid4().hex}"
            }
        }

        mock_intent.return_value = IntentResult(
            intent="order_status",
            reason="查询订单状态，但缺少订单号",
        )

        # 第一轮：保存等待订单号的任务
        r1 = self.invoke(config, "帮我查询订单状态")
        pending = r1["pending_intent"]
        self.assertIsNotNone(pending)

        # 第二轮：模型失败，不能清空 pending_intent
        mock_intent.side_effect = TimeoutError("Qwen timeout")
        r2 = self.invoke(config, "我想问点其他事情")

        self.assertEqual(r2["pending_intent"], pending)
        self.assertIn("稍后重试", r2["messages"][-1].content)

        # 第三轮：继续原任务的参数澄清
        r3 = self.invoke(config, "我不知道订单号在哪里找")

        self.assertEqual(
            r3["intent_result"]["intent"],
            "order_status",
        )
        self.assertEqual(r3["pending_intent"], pending)
        self.assertIn("我的订单", r3["messages"][-1].content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
