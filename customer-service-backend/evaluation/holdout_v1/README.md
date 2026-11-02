# 留出方法示例与公开回归数据

保留 24 个场景、38 轮输入、独立 labels、输入校验和评分器。原业务 MySQL worker 已排除，不能在本仓库一键重演原完整系统留出评测。

`input_validation.py` 拒绝输入携带标签/额外字段/非法回放；`score.py` 只对外部实际记录执行确定性断言，不能依据“操作成功”的模型文本授予成功。默认评分模式为 offline-grading/unverified-adapter，不暗示真实模型或数据库。固定历史价格不再用于推算费用。

本轮只运行 8 项 schema/评分器测试，不是 24 场景模型调用。输入与 labels 保持字节不变；不为提高分数修改标签。设计者了解开发缺陷与类别，非 IID 生产分布；样本已公开，不再作为新的独立盲测。

从仓库根目录运行：`cd customer-service-backend/evaluation/holdout_v1 && ../../../.venv/bin/python -m unittest test_holdout -v`。
外部重测需自己提供隔离执行器与结果记录、冻结模型/代码/规则哈希，预测器只接收输入，不读取 labels，结束后再独立评分。这里提供方法与数据，不伪造可运行的真实 MySQL 流程。
