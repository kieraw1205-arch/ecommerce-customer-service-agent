"""E3-07 最终边界测试：不调用真实 Qwen。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from my_agent.nodes import recognize_intent_node


class TestE3Final(unittest.TestCase):

    def make_state(self, message, pending=None, workflow=None):
        return {
            "messages": [HumanMessage(content=message)],
            "pending_intent": pending,
            "pending_workflow": workflow,
        }

    def test_invalid_workflow_resume(self):
        """损坏的工作流不能导致崩溃。"""
        workflow = {
            "status": "pending",
            "current_step": 5,
            "tasks": [{"intent": "order_status"}],
        }

        result = recognize_intent_node(
            self.make_state("继续", workflow=workflow)
        )

        self.assertEqual(
            result["intent_result"]["intent"],
            "unclear",
        )
        self.assertIsNone(result["pending_workflow"])

    def test_empty_workflow_resume(self):
        """空任务列表不能恢复。"""
        workflow = {
            "status": "pending",
            "current_step": 0,
            "tasks": [],
        }

        result = recognize_intent_node(
            self.make_state("继续", workflow=workflow)
        )

        self.assertIsNone(result["pending_workflow"])

    @patch(
        "my_agent.nodes.recognize_intent",
        side_effect=TimeoutError("Qwen timeout"),
    )
    def test_timeout_preserves_pending(self, mock_llm):
        """模型失败不能清理原有待办任务。"""
        pending = {
            "intent": "order_status",
            "order_id": None,
        }

        result = recognize_intent_node(
            self.make_state(
                "我想问个其他问题",
                pending=pending,
            )
        )

        self.assertEqual(
            result["intent_result"]["reason"],
            "intent_recognition_failed",
        )
        self.assertNotIn("pending_intent", result)
        self.assertNotIn("pending_workflow", result)

    @patch("my_agent.nodes.recognize_intent")
    def test_ab_order_id_slot_filling(self, mock_llm):
        """A、B 和小写订单号均应确定性补全。"""
        for raw, expected in [
            ("A20260410001", "A20260410001"),
            ("B20260409001", "B20260409001"),
            ("b20260409001", "B20260409001"),
        ]:
            with self.subTest(order_id=raw):
                pending = {
                    "intent": "order_status",
                    "order_id": None,
                }

                result = recognize_intent_node(
                    self.make_state(raw, pending=pending)
                )

                self.assertEqual(
                    result["intent_result"]["order_id"],
                    expected,
                )
                self.assertIsNone(result["pending_intent"])

        mock_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
