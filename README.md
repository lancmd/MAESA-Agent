# Intelligent Agent for Mining Area Ecological Space Analysis

面向矿区本地遥感影像分类、PLUS 情景模拟、InVEST 碳储量和生态服务分析的执行型 Skill。MCP 在本项目中只是一层本地工具协议：Agent 将结构化任务交给同一台机器上的 Python 进程、桌面软件或本地桥接器。服务默认监听 `127.0.0.1`，不把 ArcGIS Pro、ENVI、PLUS 或 InVEST 暴露为公网控制服务。

## 安装到 Agent 平台

先把仓库安装为 Skill。以下命令适用于 Codex Desktop 的 Windows PowerShell：

```powershell
npx skills add lancmd/MAESA-Agent -g
```

如果 Windows 环境中没有 `npx` 或 `node`，可以临时使用 Codex 管理的 Node.js 运行时：

```powershell
$runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$env:PATH = (Join-Path $runtimeRoot 'node\bin') + ';' + (Join-Path $runtimeRoot 'native\git\cmd') + ';' + $env:PATH
& (Join-Path $runtimeRoot 'bin\fallback\pnpm.cmd') dlx skills add lancmd/MAESA-Agent -g
```

进入安装后的 Skill 目录，再初始化本地运行环境并启动 MCP 服务：

```powershell
.\scripts\setup_agent.ps1 -WithPyTorch
.\scripts\start_agent_mcp.ps1
```

`agents/openai.yaml` 指向本机地址 `http://127.0.0.1:8765/mcp`。在 Agent 平台刷新 Skill 或重新打开会话后，智能体即可发现工具。服务仅供本机 Agent 使用；不要将该端口映射到公网或设置为外网回调地址。

### 本地软件边界

安装 Skill 并不等于所有软件都已可执行。启动前可运行 `python scripts/verify_agent_install.py` 查看本地环境和后端注册表。

| 能力 | 可执行条件 |
|---|---|
| PyTorch 分类 | 已安装可选依赖，并提供可验证的模型包和本地影像。 |
| ArcGIS Pro / InVEST | 本机已安装并能被适配器探测到。 |
| ENVI | 本机有有效许可，且本地 ENVI 桥接器已启动。 |
| PLUS | 本机有可用版本及对应的本地桥接器；缺少桥接器时项目只能准备输入和任务包，不能宣称已完成预测。 |

桥接器、许可或交互登录尚未就绪时，工具会返回 `prepared`、`waiting_interactive` 或 `failed`，并保留日志。它不会尝试远程控制软件，也不会绕过商业软件许可。

## 快速开始（手动部署）

```powershell
Copy-Item interfaces/backend_registry.example.json interfaces/backend_registry.json
python -m pip install -e "mcp_server[validation]"
mining-gis-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

需要运行本地 PyTorch 分类时安装可选依赖：

```powershell
python -m pip install -e "mcp_server[pytorch]"
```

`interfaces/backend_registry.json` 只注册本地命令、回环 socket 或回环 HTTP 后端。默认示例使用命令后端；ENVI 可接本地 socket。请通过环境变量或 `config/local_paths.example.json` 提供本机软件路径，不要把个人磁盘路径写入共享配置。没有 MCP 客户端时，仍可使用 `scripts/workflow_agent.py` 作为本地入口。

## 本地项目主流程

以 `templates/local_project.json` 建立项目：用户提供本地遥感影像、ROI、矿区边界、碳密度、PLUS 驱动因子，以及可选训练 ROI、PyTorch 模型、DEM、`w.dat`/沉陷深度和生态服务指标表。先检查项目配置：

```powershell
python scripts/project_validator.py --project <project.json>
python scripts/project_workflow.py --project <project.json> --run
```

第二条命令从同一份项目配置生成并运行工作流，不需要手工维护 `workflow_job.json`。项目后端会按设置选择 ENVI 或 PyTorch 分类，运行 PLUS、InVEST、沉陷积水库容和 Min-Max/AHP 生态服务。生态服务可组合碳储量、年水源供给和生境质量，并支持水源供给校准、协同/权衡、情景比较、敏感性与 GeoDetector 归因。PLUS 默认输出 ND（自然发展）、UD（城镇发展）、EP（生态保护）和 RE（资源开采）四种情景；RE 使用经外部概率积分法软件计算、转换并对齐后的正下沉深度 TIF 作为核心驱动，同时保留其他驱动因子。

`examples/huaibei_demo/` 提供匿名合成数据生成器、可验证项目配置、期望输出和基准指标。它用于检查安装与执行链，不代表真实矿区结论。

空间结果可交给 ArcGIS Pro 的 `compose_layout` 处理。它在已有 `.aprx` 和布局模板的副本中添加任务列出的成果图层、应用 `.lyrx` 符号、更新标题与地图范围，并导出 PDF/PNG 和布局验证 JSON。布局验证会检查图层、图例元素、范围和分辨率；颜色、标签、顺序和遮挡仍需打开导出的 PDF/PNG 做视觉复核。

## 目录

- `scripts/`：本地执行器、项目编译器和软件适配脚本。
- `deep_learning/`：PyTorch 模型包、推理和精度控制规范。
- `mcp_server/`：仅监听本机的 MCP 工具服务。
- `interfaces/`：本地桥接协议与后端注册表示例。
- `execution/`：执行契约与后端能力边界。
- `templates/`：项目、任务和 ArcGIS 操作清单模板。
- `config/`：分类体系、数据源、矿区类型规则和本地路径示例。
- `envi_classification/`、`arcgis_steps/`、`plus_model/`、`invest_carbon/`、`ecosystem_service/`：领域流程与参数说明。
- `open_gis_workflows/`：开放 GIS 数据处理与验证规范。

常用本地模板：`templates/local_project.json`、`templates/arcgis_module_outputs.json`、`templates/ecosystem_service_config.json`。沉陷积水库容使用基准 DEM、正下沉深度栅格、遥感积水边界和水面高程；`w.dat` 先标准化为下沉深度，不能直接当作水深。启用沉陷积水复合碳库计算后，ArcGIS 会输出库容、水体碳、水生植被碳和底泥碳，并以复合碳库替换 InVEST 的沉陷积水面积碳。

源数据保持只读，派生文件写入项目自己的 `workspace`。
