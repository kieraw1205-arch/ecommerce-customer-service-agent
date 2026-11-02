# 保留文件的来源复核

以下是逐文件工程来源记录，不单以目录或新增时间认定原创。候选文件的初始基线同路径均不存在；跨基线连续八行（去空白/注释/导入、至少160字符）片段比对无匹配；此前跨路径较大函数/类精确 AST 比对无匹配。另按职责复核了 Graph/状态、工具与目标校验、确认工作流、Trace、安全、测试及评分实现，并排除了依赖课程服务端的执行分支。
这些比对不能识别所有改写，也不构成法律归属保证。项目有课程学习背景；协议路径/字段是用于兼容的接口事实，服务端表达实现与素材未复制进公开树。原始私有提交对照只保存在私有审计记录，不公开作者邮箱或历史引用。

| 保留路径 | 来源与处理 |
|---|---|
| `customer-service-backend/evaluation/evaluate_agent.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/evaluation/evaluation.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/evaluation/holdout_v1/inputs.json` | 项目开发增量；复核后保留 |
| `customer-service-backend/evaluation/holdout_v1/labels.json` | 项目开发增量；复核后保留 |
| `customer-service-backend/evaluation/holdout_v1/score.py` | 项目评分器；移除真实 MySQL 模式暗示与固定历史费用估算 |
| `customer-service-backend/evaluation/holdout_v1/test_holdout.py` | 项目断言测试；输入校验改从不依赖业务服务的纯函数导入 |
| `customer-service-backend/evaluation/scenarios.json` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/__init__.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/api_client.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/app.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/audit.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/checkpoint.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/contracts.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/evaluate_adapter.py` | 项目意图评估增量；删除依赖私有 MySQL 的任务执行部分 |
| `customer-service-backend/my_agent/graph.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/intent.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/llm.py` | 本批独立简化为显式环境变量模型客户端；移除 dotenv 搜索与旧交互示例 |
| `customer-service-backend/my_agent/multi_read.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/nodes.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/product_knowledge.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/prompts.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/query_flow.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/refund_workflow.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/router.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/routing.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/runtime.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/security.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/shipping_workflow.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/state.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/task_transition.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/telemetry.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/tool_calling.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/tools.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/my_agent/workflow_validation.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/scripts/test_all.py` | 项目离线测试入口；补显式假配置与子进程导入路径 |
| `customer-service-backend/tests/test_batch2_api.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_batch2_business.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_edge_cases.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_final.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_graph_errors.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_model_errors.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_multiturn.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_persistence.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_regression.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_routing.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e3_state_recovery.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e4_api.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e4_edges.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_e4_workflow.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_evaluation.py` | 项目开发增量；复核后保留 |
| `customer-service-backend/tests/test_telemetry.py` | 项目开发增量；复核后保留 |

新编文件：本批配置/依赖锁/白名单、`examples/offline_demo.py`、`tests/test_preview.py`、README 与 docs、NOTICE、Dockerfile 均按精简运行契约编写。`holdout_v1/input_validation.py` 是从本项目新增 worker 抽取的纯输入校验函数，不携带课程 ORM/API。没有保留旧 Vue/SVG/图片或其截图。

依赖来源：`requirements.lock` 从已验证安装的发行元数据递归提取运行时闭包，49 个分发包，未包含任何私有 URL/路径依赖。`docs/dependencies.json` 记录版本与许可；不捆绑库源码或已构建镜像。Python 基础镜像与三方发行包的许可分别适用。

公开树不保留原完整系统日志/指标文件和部署种子脚本；数据集中订单/用户/商品标识是虚构测试文本，不是生产业务数据。后续新增依赖和同步变更仍需审查，不应将本次结论套用到所有未来版本。
