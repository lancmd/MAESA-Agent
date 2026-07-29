<p align="center">
  <img src="assets/maesa-banner.svg" alt="MAESA Agent" width="100%" />
</p>

<p align="center"><strong>MAESA Agent · Local-first mining ecological analysis</strong></p>

# MAESA Agent

MAESA（Mining Area Ecological Space Analysis）把矿区遥感与生态服务研究组织成可验证的本地工作流。用户提供本地数据和 `project.json`，Agent 校验空间数据、编译可恢复任务、调用已安装的软件并记录全部成果来源。

它覆盖多期土地利用分类、转移 Sankey、PLUS ND/UD/EP/RE、InVEST 碳储量/水源供给/生境质量、沉陷积水复合碳库、生态服务评价和 ArcGIS Pro 出图。

> **Local-first。** MCP 仅连接本机服务；ArcGIS Pro、ENVI、PLUS 和 InVEST 不接受公网远程控制。云端 LLM 如被启用，也只负责受约束的文本规划。

## 能力边界

| 模块 | 本机实现 | 结果 |
|---|---|---|
| 项目构建、空间预检、清单和续跑 | Python | 自动 |
| ENVI 监督分类 | IDL/ENVI 桥接 | 需本机许可 |
| PyTorch 分类 | 分割模型或已登记 ResNet-50 图块分类器 | 后者须独立验证 |
| PLUS 四情景 | 官方快照 GUI 桥接 | 首次须校准界面 |
| InVEST 与生态服务 | 本机 CLI/Python | 输入完整时自动 |
| 制图与沉陷库容 | ArcPy / ArcGIS Pro | 需本机许可 |

`prepared`、`waiting_interactive` 和 `pending_validation` 均表示尚未完成，不会被写成分析成功。

## 快速开始

```powershell
npx skills add lancmd/MAESA-Agent -g
cd MAESA-Agent
.\scripts\setup_agent.ps1 -WithPyTorch -WithPlusGui
.\scripts\start_agent_mcp.ps1
```

创建或检查项目：

```powershell
python .\scripts\project_validator.py --project .\project.json
python .\scripts\project_workflow.py --project .\project.json --run
```

工作流会生成 `workspace/generated/workflow_job.json`；用户无需手写 job 文件。也可以由 Copilot 根据已审核的本地输入清单创建确认式执行计划，详见 [项目与 Copilot](docs/project.md)。

## 最小数据交接

按任务启用模块，而不是一次性提供全部数据。

- 分类：各期影像，逐期 ROI 或模型包，以及独立验证样本；
- PLUS：至少两期对齐 LULC、驱动因子、矿区边界；RE 还需要正向下沉陷深度栅格或受约束的 `w.dat`；
- Carbon：LULC 和覆盖全部类别编码的碳密度 CSV；
- Water Yield：降水、ET0、土壤层、流域和生物物理表；
- Habitat Quality：威胁因子栅格、威胁表和敏感性表；
- 制图：可选 `.aprx`、布局和 `.lyrx`。

完整字段与任务模式见 [项目与 Copilot](docs/project.md)，分类样本和传感器参数见 [分类与精度](docs/classification.md)。

## 本机软件

个人路径写入被忽略的 `config/local_paths.json` 或环境变量，不提交到仓库。

| 软件 | 环境变量 |
|---|---|
| ArcGIS Pro | `ARCGIS_PROPY`、`ARCGIS_PRO_EXE` |
| ENVI / IDL | `IDL_EXE` |
| PLUS | `PLUS_V142_EXECUTABLE` |
| InVEST | `INVEST_CLI` |

运行 `python .\scripts\workflow_agent.py probe` 查看本机可用能力。

## 验证与发布前测试

每个项目产生 `outputs_manifest.json`、`provenance.json`、`validation_summary.json` 和 `agent_state.json`。验收包括 LULC 的 OA/F1/IoU、PLUS 的 FoM/类别精度/随机种子稳定性、InVEST 一致性、生态服务敏感性和地图图层/范围/分辨率检查。

```powershell
python -m pytest .\tests\test_smoke_suite.py -q
python .\tests\mcp_smoke.py
```

GitHub Actions 会在 Windows Python 3.11 和 3.12 上运行上述可移植测试；商业 GIS 软件仅在本机小栅格测试。

## 目录

```text
MAESA-Agent/
├── agents/       # Agent 客户端连接定义
├── config/       # 本机路径与 GUI 配置示例
├── docs/         # 七份任务中心文档
├── mcp_server/   # 本地 MCP 服务
├── scripts/      # 工作流编译器和软件桥接
├── templates/    # 项目与数据栈模板
├── examples/     # 匿名合成示例
└── tests/        # 可移植与本机集成测试
```

MAESA-Agent 0.4.0 采用 [MIT License](LICENSE)。它编排已安装的软件，不分发 ArcGIS Pro、ENVI、PLUS 或 InVEST 的许可，也不替代独立的数据和科研验证。
