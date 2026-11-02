"""复合任务工作流状态验证。"""


def validate_pending_workflow(workflow: dict | None) -> tuple[bool, str]:
    """验证待恢复工作流的数据结构。"""

    if not isinstance(workflow, dict):
        return False, "工作流不存在或格式错误"

    if workflow.get("status") != "pending":
        return False, "工作流不处于待处理状态"

    tasks = workflow.get("tasks")

    if not isinstance(tasks, list) or not tasks:
        return False, "工作流没有有效的子任务"

    current_step = workflow.get("current_step")

    if type(current_step) is not int:
        return False, "工作流步骤编号无效"

    if not 0 <= current_step < len(tasks):
        return False, "工作流步骤超出范围"

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            return False, f"第 {index + 1} 个子任务格式错误"

        if not isinstance(task.get("intent"), str) or not task["intent"].strip():
            return False, f"第 {index + 1} 个子任务缺少有效意图"

    return True, ""
