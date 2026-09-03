---
name: mining-area-ecological-space-analysis
description: 在本机完成矿区多期土地利用分类、PLUS 情景预测、InVEST 生态系统服务评价、论文制图与受控成果归档；适用于用户提供本地项目数据并要求检查、运行、续跑或整理成果的任务。
---

# MAESA Agent

这是一个 local-first Skill：MCP、软件桥接和空间数据都留在用户电脑上。读取项目后，按已启用模块收集输入；不要为简单任务强行索取完整链条数据。

1. 无项目文件时从 `templates/local_project.json` 创建；先调用后端能力探测，再运行 `inspect_local_project_readiness`。该检查会验证、编译并检查本地数据，但不会启动商业软件。
2. 只运行编译得到的工作流，并保留 `agent_state.json`、`outputs_manifest.json`、`provenance.json` 和 `validation_summary.json`。
3. 所有空间处理以项目声明的主网格为准。分类需要独立验证样本；没有验证时状态为 `pending_validation`，不能当作完成结果。
4. PLUS 的 ND、UD、EP、RE 分别使用独立目录。未完成 GUI 校准或尚未识别输出时保持 `prepared` 或 `waiting_interactive`，不虚报完成。
5. InVEST 和跨期统计只使用同一六类编码与明确的共同有效支撑区；沉陷积水和自然水体不得合并，连续栅格和分类栅格不得混用重采样方法。
6. 只读取 `security.input_roots` 内的源数据，只向 `workspace` 写入；覆盖已有输出前要求确认。
7. 最终交付前将地图、图表、报告、原生模型输出和运行清单归档到一个目录。先生成清理预览；仅在用户确认的范围内删除旧派生成果，永不清理原始输入目录。

按任务查阅：

- [项目、输入与 Copilot](docs/project.md)
- [分类与精度](docs/classification.md)
- [空间预处理与 ArcGIS](docs/spatial.md)
- [PLUS 情景](docs/plus.md)
- [InVEST 与生态服务](docs/invest-ecosystem.md)
- [本机运行与状态](docs/runtime.md)
- [数据和分类参考](docs/reference-data.md)
- [最终成果归档与清理](docs/results.md)
