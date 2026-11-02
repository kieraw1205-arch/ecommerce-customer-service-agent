"""E3-07：复合工作流异常边界测试。"""

import unittest

from my_agent.nodes import business_node


class TestWorkflowEdgeCases(unittest.TestCase):

    def make_state(self, workflow):
        return {
            "intent_result": {
                "intent": "multi_intent",
                "reason": "用户希望继续之前保存的复合任务",
                "sub_intents": [],
            },
            "pending_workflow": workflow,
            "messages": [],
        }

    def check_safe_response(self, workflow):
        result = business_node(self.make_state(workflow))

        self.assertIn("messages", result)
        self.assertTrue(result["messages"])
        self.assertTrue(result["messages"][0].content)

        # 异常工作流不能被误标记为已完成
        self.assertNotEqual(
            (result.get("pending_workflow") or {}).get("status"),
            "completed",
        )

    def test_empty_tasks(self):
        self.check_safe_response({
            "status": "pending",
            "current_step": 0,
            "tasks": [],
        })

    def test_step_out_of_range(self):
        self.check_safe_response({
            "status": "pending",
            "current_step": 5,
            "tasks": [
                {
                    "intent": "order_status",
                    "order_id": "A20260410001",
                    "status": "pending",
                }
            ],
        })

    def test_missing_task_intent(self):
        self.check_safe_response({
            "status": "pending",
            "current_step": 0,
            "tasks": [
                {"status": "pending"}
            ],
        })

    def test_missing_tasks_field(self):
        self.check_safe_response({
            "status": "pending",
            "current_step": 0,
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
