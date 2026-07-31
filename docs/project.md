# 项目、输入与 Copilot

`templates/local_project.json` 是项目配置的唯一模板，`schemas/` 定义结构约束。先启用任务模式，再填写该模式所需输入；未启用的模块不应阻断项目验证。

| 任务模式 | 主要输入 | 主要成果 |
|---|---|---|
| `classification_only` | 影像、ROI 或模型、验证样本 | LULC、精度报告 |
| `lulc_change_analysis` | 多期 LULC | 转移表、Sankey |
| `plus_only` | 多期 LULC、驱动因子 | ND/UD/EP/RE 图 |
| `invest_only` | LULC、相应 InVEST 数据栈 | 单模型或多模型成果 |
| `classification_invest` | 多期分类输入、碳密度/数据栈 | 分类、Carbon、Habitat 等 |
| `ecosystem_service_only` | 服务指标表、权重配置 | 综合评分与比较 |
| `mapping_only` | 已有阶段成果、布局资源 | PDF/PNG 图件 |
| `full_chain` | 已启用模块的全部输入 | 完整可恢复链条 |

## 输入与输出

源数据放入 `security.input_roots`，运行成果仅写入 `workspace`。项目编译后自动生成 `workflow_job.json`；不要手工维护第二份工作流。每次运行至少检查：CRS、主网格、NoData、分类编码、碳密度覆盖和所有前置阶段输出。

输出清单、参数、软件版本、输入哈希、随机种子和验证状态分别写入 `outputs_manifest.json`、`provenance.json` 与 `validation_summary.json`。

## 开跑前就绪检查

在启动 ENVI、PLUS、InVEST 或 ArcGIS Pro 前执行：

```powershell
python .\scripts\project_readiness.py --project .\project.json
```

它会生成 `workspace/validation/project_readiness.json`。报告包含真实输入文件的大小和 SHA-256、空间预检、逐期 ROI/独立验证样本检查、工作流阶段、计划输出及本机软件探测。`completed` 表示可以启动；`prepared` 表示数据已检查但缺少本机软件；`pending_validation` 表示可运行但分类精度尚缺独立验证；`failed` 表示应先修复报告中的输入或契约错误。

## Copilot 的受控创建

1. 建立本地输入清单；
2. Copilot 生成符合 schema 的创建计划；
3. 显示输入、步骤和输出；
4. 用户确认后才调用 allowlist MCP 工具；
5. 验证、编译、运行并汇总成果。

Copilot 没有任意 Shell 权限，也不会把本机 GIS 软件暴露到公网。
