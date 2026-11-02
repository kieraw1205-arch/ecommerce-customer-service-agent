"""E3-07：多轮对话与任务状态回归测试。"""

import re
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from my_agent.graph import graph
from my_agent.nodes import (
    is_pending_help_request,
    is_workflow_resume_request,
)
from my_agent.task_transition import get_task_state_updates


class TestStateRules(unittest.TestCase):
    """不调用 Qwen 的状态管理单元测试。"""

    def setUp(self):
        self.workflow = {
            "status": "pending",
            "current_step": 0,
            "tasks": [
                {
                    "intent": "order_status",
                    "order_id": "A20260410001",
                    "condition": None,
                    "status": "pending",
                },
                {
                    "intent": "shipping_reminder",
                    "order_id": "A20260410001",
                    "condition": "订单未发货",
                    "status": "pending",
                },
            ],
        }

    def test_pending_help(self):
        pending = {"intent": "order_status", "order_id": None}
        self.assertTrue(
            is_pending_help_request("我不知道订单号在哪里找", pending)
        )

    def test_resume_existing_workflow(self):
        self.assertTrue(
            is_workflow_resume_request("那接下来呢？", self.workflow)
        )

    def test_cannot_resume_missing_workflow(self):
        self.assertFalse(
            is_workflow_resume_request("继续", None)
        )

    def test_cancel_clears_tasks(self):
        updates = get_task_state_updates(
            {"intent": "cancel"},
            "cancel",
            self.workflow,
        )
        self.assertIsNone(updates["pending_intent"])
        self.assertIsNone(updates["pending_workflow"])

    def test_independent_task_clears_workflow(self):
        updates = get_task_state_updates(
            {"intent": "order_list", "user_id": "u1002"},
            "query",
            self.workflow,
            independent_request=True,
        )
        self.assertIsNone(updates["pending_workflow"])

    def test_new_task_without_id_clears_workflow(self):
        updates = get_task_state_updates(
            {"intent": "order_status", "order_id": None},
            "clarify",
            self.workflow,
            independent_request=True,
        )
        self.assertIsNone(updates["pending_workflow"])
        self.assertNotIn("pending_intent", updates)

    def test_unclear_request_preserves_workflow(self):
        updates = get_task_state_updates(
            {"intent": "unclear"},
            "clarify",
            self.workflow,
        )
        self.assertNotIn("pending_workflow", updates)

    def test_order_id_format(self):
        pattern = r"[AB]\d{11}"
        for order_id in (
            "A20260410001",
            "B20260409001",
            "b20260409001",
        ):
            with self.subTest(order_id=order_id):
                self.assertIsNotNone(
                    re.fullmatch(pattern, order_id.upper())
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
