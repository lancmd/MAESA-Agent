# 矿区生态空间分析智能体

这个仓库把矿区土地利用分类、PLUS 情景预测、InVEST 碳储量、沉陷积水碳库、生态服务评价和 ArcGIS Pro 制图组织成一个本地工作流。MCP 只连接同一台电脑上的进程；不会把桌面软件开放到公网。

## 安装与启动

在 Windows PowerShell 中安装 Skill：

```powershell
npx skills add lancmd/MAESA-Agent -g
```

若系统没有 Node.js，可使用 Codex 自带运行时：

```powershell
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$env:PATH = (Join-Path $runtime 'node\bin') + ';' + (Join-Path $runtime 'native\git\cmd') + ';' + $env:PATH
& (Join-Path $runtime 'bin\fallback\pnpm.cmd') dlx skills add lancmd/MAESA-Agent -g
```

进入 Skill 目录后执行：

```powershell
.\scripts\setup_agent.ps1 -WithPyTorch
.\scripts\start_agent_mcp.ps1
```

MCP 只绑定 `127.0.0.1`、`localhost` 或 `::1`。软件路径来自系统 `PATH`、环境变量或未提交的 `config/local_paths.json`；可从 [local_paths.example.json](config/local_paths.example.json) 复制配置。

## 从项目配置运行

从 [local_project.json](templates/local_project.json) 复制出 `project.json`，启用需要的模块并填写输入路径，然后运行：

```powershell
python scripts/project_validator.py --project project.json
python scripts/project_workflow.py --project project.json --run
```

模板默认不启用任何分析模块。分类只需要影像和对应的 ENVI ROI 或 PyTorch 模型包；已有 LULC、生态服务或积水库容项目不会被要求填写无关影像、ROI、矿界或碳密度表。

`security.input_roots` 列出可读数据目录，`security.output_root` 约束工作目录。派生文件只写入 `workspace`，UNC 路径、`..` 越界写入和覆盖源输入都会被拒绝。对已有派生文件进行覆盖时，加 `--confirm-overwrite`。

## PLUS 四情景与续跑

启用 PLUS 后，编译器为 ND、UD、EP、RE 分别建立独立目录：

```text
workspace/outputs/plus/ND/PLUS_ND.tif
workspace/outputs/plus/UD/PLUS_UD.tif
workspace/outputs/plus/EP/PLUS_EP.tif
workspace/outputs/plus/RE/PLUS_RE.tif
```

每个目录有独立请求包和状态记录。已核对的 **PLUS V1.4.1 boxed** 发行包使用桌面 GUI 和 `Parameterfile` 持久化参数，没有公开、可验证的批处理预测命令。复制示例配置后，在未提交的 `config/local_paths.json` 中填写本机路径：

```json
{
  "plus_v141_executable": "C:\\path\\to\\PLUS v1.4.1_boxed.exe",
  "plus_bridge_command": ["{python}", "{skill_root}/scripts/plus_v141_bridge.py"]
}
```

该桥接器会无参数启动本机 GUI，并在每个情景目录生成独立的交接清单、请求包和状态记录；它不声称已完成预测。按照交接清单在 GUI 中导出结果到上述固定位置后，再次运行同一项目，工作流会自动检查 CRS、网格、整数编码、类别代码和碳密度覆盖，并接管后续 InVEST 与生态服务阶段。若未来获得厂商提供的 CLI/API，可将 `plus_bridge_command` 改为对应的本地命令桥接器。

RE 情景只使用统一的 `resource_extraction` 契约：`core_driver_input`、`core_driver_unit: "m"`、`core_driver_convention: "positive_down"`。项目模板可用 `inputs.subsidence_depth_raster` 作为简写，桥接器实际收到的是已解析的对齐 TIFF；`w.dat` 只是外部沉陷计算的来源记录。

## 情景闭环与验收

当 PLUS、InVEST 与生态服务同时启用时，工作流按下面的依赖执行：

```text
PLUS_ND/UD/EP/RE → InVEST Carbon_ND/UD/EP/RE
                 → 情景碳储表 → 生态服务评分、权衡、敏感性、情景比较、GeoDetector
```

分类阶段可接入独立验证样本 CSV，并自动生成 `lulc_accuracy.json` 和 `confusion_matrix.csv`（OA、Macro-F1、Macro-IoU 与各类别 precision/recall/F1/IoU）。样本含 `x_field`、`y_field` 时，工作流直接从新生成的 LULC 栅格抽取预测类别；否则可使用样本表中已有的预测列。PLUS 输出通过空间预检；回算精度与多随机种子 FoM 可用 `validate_plus_backcast` 单独接入。生态服务阶段根据配置运行 Min-Max 或 AHP，并输出敏感性、权衡、情景比较和可选 GeoDetector 结果。

每次运行结束，工作目录都会写出：

- `outputs_manifest.json`：成果文件、类型、大小、SHA-256 和可用的空间元数据；
- `provenance.json`：输入与模型哈希、参数、随机种子、软件探测结果和阶段时间；
- `validation_summary.json`：阶段状态与验证文件清单。

独立验证仍然有其边界：PLUS 的 FoM 需要回算参考图和多个种子结果；InVEST 一致性需要独立运行结果；地图的颜色、标签和遮挡需要查看导出的 PDF/PNG。

## 示例与目录

[examples/huaibei_demo](examples/huaibei_demo) 是合成数据演示，不含真实矿区结论。核心实现位于 `scripts/`；领域方法和操作说明位于 `plus_model/`、`invest_carbon/`、`ecosystem_service/`、`arcgis_steps/` 与 `envi_classification/`。
