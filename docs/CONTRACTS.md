# 外部业务 API 契约（不包含服务端实现）

事实字段/接口协议用于集成，不携带课程服务端源码。客户端模型见 `my_agent/contracts.py`，错误映射见 `my_agent/api_client.py`。下列是预览期既有协议，不是公开版本已经提供的可访问服务。

通用响应：`{"code":0,"data":{...}}`；标识符仅接受 1–64 位字母数字、下划线或连字符。每个请求携带当前认证主体的 bearer 凭据，可携带 `X-Trace-ID`。服务端必须自己验证归属，禁止按订单号直接读取任意用户订单。

| HTTP | 路径 | 数据字段 / 约束 |
|---|---|---|
| GET | `/users/{user_id}/orders` | user_id、orders[]（order_id/title/status/amount/created_at） |
| GET | `/orders/{order_id}/status` | order_id、status、status_desc |
| GET | `/orders/{order_id}/logistics` | 上述状态、logistics_company、tracking_number、traces[time/desc] |
| GET | `/products/{product_id}` | product_id/title/description/price/stock_status/attributes |
| GET | `/users/{user_id}/products` | user_id、products[]；仅本人 |
| GET | `/orders/{order_id}/shipping-reminders/{request_id}` | 原请求回执或明确 404；协议头必需 |
| POST | `/orders/{order_id}/shipping-reminders` | confirmed=true、request_id、expected_status、提交说明；只允许合法状态 |
| GET | `/orders/{order_id}/refund-applications/{request_id}` | 原退款申请回执或明确 404；协议头必需 |
| POST | `/orders/{order_id}/refund-applications` | confirmed=true、request_id、expected_status、用户提供的 reason |

催发货读回执头 `X-Shipping-Protocol`、退款头 `X-Refund-Protocol` 为 `confirmed-idempotency-v1`；协议不匹配时客户端拒绝写。催发货请求 ID 为 U + 32 位十六进制，退款为 R + 32 位十六进制。外部服务需以认证用户、目标、请求标识和内容执行原子校验与幂等，返回原请求回执。HTTP 401/403/404/409/422/5xx、超时及畸形响应有独立失败类别；写超时可能结果未知，不能自动重试成新请求。

本仓库不提供真实扣款/退款到账、业务 MySQL 或生产级服务器。离线响应仅作为模型边界和契约示例，不能替代服务端权限与事务测试。
