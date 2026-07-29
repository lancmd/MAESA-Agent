---
name: mining-area-ecological-space-analysis
description: 在本机完成矿区多期土地利用分类、PLUS 情景预测、InVEST 碳储量与生态服务评价、沉陷积水核算及 ArcGIS Pro 制图。
---

# MAESA Agent

这是一个 local-first Skill：MCP、软件桥接和空间数据都留在用户电脑上。读取项目后，按已启用模块收集输入；不要为简单任务强行索取完整链条数据。

1. 无项目文件时从 `templates/local_project.json` 创建；先调用后端能力探测，再验证和编译项目。
2. 只运行编译得到的工作流，并保留 `agent_state.json`、`outputs_manifest.json`、`provenance.json` 和 `validation_summary.json`。
3. 所有空间处理以项目声明的主网格为准。分类需要独立验证样本；没有验证时状态为 `pending_validation`，不能当作完成结果。
4. PLUS 的 ND、UD、EP、RE 分别使用独立目录。未完成 GUI 校准或尚未识别输出时保持 `prepared` 或 `waiting_interactive`，不虚报完成。
5. 只读取 `security.input_roots` 内的源数据，只向 `workspace` 写入；覆盖已有输出前要求确认。

按任务查阅：

- [项目、输入与 Copilot](docs/project.md)
- [分类与精度](docs/classification.md)
- [空间预处理与 ArcGIS](docs/spatial.md)
- [PLUS 情景](docs/plus.md)
- [InVEST 与生态服务](docs/invest-ecosystem.md)
- [本机运行与状态](docs/runtime.md)
- [数据和分类参考](docs/reference-data.md)
