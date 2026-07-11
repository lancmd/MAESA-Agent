# 执行状态与恢复

后端响应只使用以下状态：

| 状态 | 含义 |
|---|---|
| `accepted` | 本地异步任务已接收 |
| `running` | 本地软件正在处理 |
| `completed` | 任务成功，声明的产物存在 |
| `prepared` | 本地任务包或脚本已生成，目标软件尚未完成计算 |
| `pending_validation` | 产物存在，独立精度或人工图面核验尚未完成 |
| `waiting_interactive` | 本地许可、登录或 GUI 需要用户接管 |
| `failed` | 输入、命令、软件或产物验收失败 |
| `cancelled` | 异步任务已经取消 |

`agent_state.json` 记录各阶段的时间、命令、日志、状态与输出。再次运行时，仅跳过状态为 `completed` 且声明产物仍然存在的阶段。参数或输入改变后使用新任务 ID，避免沿用旧状态。

工作流计划中的 `ready`、`blocked` 和 `disabled` 只描述运行前计划，不是后端响应状态。项目校验使用 `valid`/`invalid`，同样不写入软件任务状态。

PLUS 没有匹配当前版本的本地桥接器时返回 `prepared`；启动 GUI 后需要接管时返回 `waiting_interactive`。两种情况都不等同于情景预测完成。
