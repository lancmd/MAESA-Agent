# MAESA Agent

**MAESA（Mining Area Ecological Space Analysis）** 是面向矿区土地利用与生态系统服务研究的本地优先（local-first）智能体工作流。它将 ENVI / PyTorch 分类、PLUS 四情景模拟、InVEST 碳储量—水源供给—生境质量评估、沉陷积水复合碳库和 ArcGIS Pro 制图组织为可追溯的本地任务。

项目不把商业 GIS 软件暴露到公网。MCP 只作为本机 Agent 与本机工具之间的受控协议；软件、原始数据、模型和结果都保留在用户电脑中。

## 能力范围

| 模块 | 本地后端 | 主要输出 | 验证状态 |
|---|---|---|---|
| 项目构建与空间预检 | Python / GDAL | `workflow_job.json`、预检报告 | 自动 |
| 土地利用分类 | ENVI 或 PyTorch | LULC、置信度、精度表 | 独立样本不足时为 `pending_validation` |
| 土地利用变化 | Python | 转移矩阵、Sankey、面积统计 | 自动 |
| PLUS | 官方 PLUS V1.4.2 GUI 桥接 | ND、UD、EP、RE LULC | 需回代 FoM / 多种子验证 |
| InVEST Carbon | InVEST | 碳库栅格、总碳储量 | 碳密度需可追溯 |
| InVEST Annual Water Yield | InVEST | 产水深、流域汇总 | 需流量或水量平衡校准 |
| InVEST Habitat Quality | InVEST | 生境质量、威胁退化 | 需威胁与样点验证 |
| 综合生态服务 | min-max + AHP | 综合指数、情景比较 | 可做权重敏感性分析 |
| 论文级成果 | ArcGIS / Matplotlib | 地图、图表、三线表、DOCX/PDF | 图面与单位检查 |

`prepared`、`waiting_interactive` 与 `pending_validation` 都不表示科研分析已经验证完成。系统会把软件运行状态、空间预检状态和独立科研验证状态分开记录。

## 安装方式

### 作为 Agent Skill 安装

```powershell
npx skills add lancmd/MAESA-Agent -g
```

安装后在支持 Skill/MCP 的 Agent 平台中启用 `mining-area-ecological-space-analysis`。这会安装工作流说明、MCP 注册信息和本地工具代码；不会替你安装 ArcGIS Pro、ENVI、PLUS、InVEST 或研究数据。

### 本地开发与正式运行

```powershell
git clone https://github.com/lancmd/MAESA-Agent.git
cd MAESA-Agent
.\scripts\setup_agent.ps1 -WithPyTorch -WithPlusGui
.\scripts\maesa_doctor.ps1
.\scripts\start_agent_mcp.ps1
```

若端口 `8765` 已被占用：

```powershell
.\scripts\start_agent_mcp.ps1 -Port 8766
```

软件路径请写入未提交的 `config/local_paths.json` 或环境变量：

| 软件 | 环境变量 |
|---|---|
| ArcGIS Pro | `ARCGIS_PROPY`、`ARCGIS_PRO_EXE` |
| ENVI / IDL | `IDL_EXE` |
| PLUS | `PLUS_V142_EXECUTABLE` |
| InVEST | `INVEST_CLI` |

## 数据交接

按任务模式提供数据，而不是强制一次性交齐所有模块：

- 分类：逐期影像、逐期 ROI 或登记的模型包；建议同时提供独立验证样本；
- 变化分析：至少两期已对齐 LULC；
- PLUS：至少两期 LULC、驱动因子、矿区边界；RE 还需与主网格对齐的 `positive_down` 沉陷深度栅格或受约束的 `w.dat`；
- Carbon：LULC 与覆盖全部编码的碳密度 CSV；
- Water Yield：降水、ET0、土层深度、PAWC、流域、Kc/根系深度表；
- Habitat Quality：威胁栅格、威胁表、敏感性表；
- 制图：可选 `.aprx`、布局模板和 `.lyrx`。

复制 [`examples/real_project_template`](examples/real_project_template/README.md) 后填写自己的绝对路径。随后执行：

```powershell
python .\scripts\project_validator.py --project .\project.json
python .\scripts\project_readiness.py --project .\project.json
python .\scripts\project_workflow.py --project .\project.json --run
```

项目编译器将生成 `workspace/generated/workflow_job.json`，用户不需要手工维护任务文件。

## 结果与可复现性

每次运行应保留：

- `outputs_manifest.json`：输出文件、类型、大小、空间信息与哈希；
- `provenance.json`：输入哈希、参数、软件版本、随机种子与时间；
- `validation_summary.json`：分类、PLUS、InVEST、生态服务和制图验证状态；
- `agent_state.json`：可暂停/续跑阶段状态。

分类评价应至少报告 OA、Macro-F1、Macro-IoU 和逐类精度；PLUS 应报告 FoM、关键地类精度及多随机种子稳定性；InVEST 应进行独立运行一致性和参数敏感性核对。只有具备这些证据后，模型结果才适合被表述为经验证的科研结果。

## 论文报告与单位核算

`scripts/build_wanbei_report_assets.py` 用正式 CSV 与 GeoTIFF重新核算历史期和四情景统计，防止把单位在制图或汇总阶段重复换算：

```powershell
.\.venv\Scripts\python.exe .\scripts\build_wanbei_report_assets.py --root C:\path\to\project
python .\scripts\build_ecosystem_service_report.py --root C:\path\to\project
```

约定如下：

- 30 m 像元面积为 `0.09 hm²`；
- `tot_c_cur.tif` 是 `Mg C/像元`，总碳储量直接求和；制图为面密度时再除以 `0.09 hm²`，单位为 `Mg C/hm²`；
- 年产水栅格为 `mm`，总水量为 `水深(mm) × 像元面积(m²) / 1000`；
- 地图连续色带必须标明单位，分类图必须只显示实际编码类别。

该报告脚本会把可验证的统计、三线表、图件、待验证项和结果边界写入 DOCX；它不会用参考论文中的示例数值替代本项目结果。

## 测试

```powershell
python -m pytest .\tests\test_smoke_suite.py -q
python .\tests\report_asset_contract_smoke.py
python .\tests\mcp_smoke.py
```

GitHub Actions 运行跨平台的 Python 合同测试。ArcGIS Pro、ENVI、PLUS 和受许可证约束的 InVEST 软件在本地小栅格案例上验收。

## 目录

```text
MAESA-Agent/
├── config/              # 本地路径、分类体系和数据源示例
├── docs/                # 项目、分类、空间、PLUS、InVEST 与运行文档
├── interfaces/          # 本地 MCP 后端与工具协议
├── mcp_server/          # 可安装的 MCP 包
├── scripts/             # 编译、桥接、统计、制图和报告脚本
├── templates/           # 项目、场景与数据栈模板
├── examples/            # 匿名示例与真实项目填写模板
└── tests/               # 可移植合同测试与本地集成测试
```

MIT License。MAESA 编排用户已经合法安装的软件，但不提供 ArcGIS Pro、ENVI、PLUS 或 InVEST 的许可证，也不替代实地调查、独立验证和工程审查。
