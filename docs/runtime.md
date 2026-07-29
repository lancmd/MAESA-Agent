# 本机运行、适配器与状态

MAESA 的 MCP 服务仅绑定 `127.0.0.1`。启动后先探测 `system.capabilities`，再选择本机可用的 ArcGIS Pro、ENVI/IDL、PyTorch、PLUS、InVEST 或开放 GIS 后端。个人路径通过环境变量或 `config/local_paths.json` 提供，不提交到仓库。

通用执行顺序是：验证项目 → 编译工作流 → 提交/运行 → 读取状态 → 验收成果。任务状态仅使用 `accepted`、`running`、`completed`、`prepared`、`pending_validation`、`waiting_interactive`、`failed` 和 `cancelled`。

后台任务写入本地 job registry，可轮询、取消和恢复。输出清单记录文件类型、大小、哈希、CRS、分辨率、软件版本、输入哈希、参数、随机种子和开始/结束时间。
