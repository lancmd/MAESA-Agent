# 本地后端协议

所有后端使用 JSON 请求/响应，并声明 `protocol_version: "1.0"`。后端清单在 `backend_registry.example.json`；MCP 先查询能力，再调用已声明的本地操作。

## 状态

| 状态 | 含义 |
|---|---|
| `accepted` | 请求已接收 |
| `running` | 本机任务正在运行 |
| `completed` | 已产生并通过该阶段检查的成果 |
| `prepared` | 已准备，等待外部软件或后续接管 |
| `pending_validation` | 产生了结果，但尚缺独立验证 |
| `waiting_interactive` | 需要本机 GUI、许可或用户操作 |
| `failed` | 任务失败，报告包含原因 |
| `cancelled` | 用户取消 |

`prepared`、`pending_validation` 与 `waiting_interactive` 都不是完成状态。MCP 仅访问本机注册的命令，不提供公网软件控制通道。
