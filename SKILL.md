---
name: mining-area-ecological-space-analysis
description: 使用本地遥感影像、ROI、矿区边界、碳密度、驱动因子和沉陷数据，通过本机 MCP 调用 PyTorch、ENVI、ArcGIS Pro、PLUS 与 InVEST，完成矿区土地利用、情景模拟、沉陷积水碳储、生态服务和制图验收。
---

# 矿区生态空间分析执行智能体

这个 Skill 面向需要实际文件、运行日志和验收记录的本地矿区项目。它把 MCP 当作智能体与本机软件之间的工具协议，不把 MCP 作为公网软件控制网络。

## 开始前

1. 读取用户的 `project.json`；没有项目文件时，从 `templates/local_project.json` 建立。
2. 调用 `list_backends` 与目标后端的 `backend_capabilities`，了解本机可用软件和桥接状态。
3. 运行 `validate_local_project`，然后调用 `compile_project_workflow`。编译结果是唯一的工作流来源，不要求用户另行维护 `workflow_job.json`。
4. 使用 `run_local_project` 运行已具备条件的阶段。PLUS 未配置本地版本桥接时，会留下本地任务包并报告 `prepared`；这不是 PLUS 预测完成。

`completed` 表示声明的产物已生成；`prepared` 表示任务包已就绪；`waiting_interactive` 表示许可或 GUI 需要接管；`pending_validation` 表示有产物但缺少独立验证；`failed` 需要说明原因并保留日志。

## 本地软件路线

| 任务 | 工具 | 产物与检查 |
|---|---|---|
| 土地利用分类 | PyTorch 或 ENVI | 分类、置信度、OA、F1、IoU、分类别精度 |
| 栅格预处理与沉陷数据 | ArcGIS Pro | 对齐栅格、坡度坡向、距离、面积、深度与库容 |
| PLUS 模拟 | 版本匹配的本地桥接器 | ND、UD、EP、RE，FoM、分类别精度和多种子稳定性 |
| 碳储量 | 本地 InVEST | Carbon datastack、输出栅格、独立运行一致性 |
| 生态服务 | 本地计算与 InVEST | 标准化范围、AHP 一致性、敏感性、权衡与情景比较 |
| 最终地图 | ArcGIS Pro | 图层、符号、标题、图例、范围、分辨率与 PDF/PNG |

本机软件路径来自环境变量、系统 PATH 或未提交的 `config/local_paths.json`。公共仓库只保留 `config/local_paths.example.json`。

## 专题规则

- 分类栅格采用最近邻处理；连续因子采用适合其量纲的连续重采样。进入 PLUS/InVEST 前，检查 CRS、像元大小、范围、行列数、NoData 和编码。
- RE 使用外部沉陷软件给出的结果。将 `w.dat`/`w.txt` 转为米单位、正值向下、与主网格对齐的 `subsidence_depth_aligned.tif`；它是核心驱动因子之一，不等同于水深或沉陷积水。
- 沉陷积水复合碳储使用预采 DEM、下沉深度、积水边界、水面高程及用户提供的三类碳密度。复合碳储替换 InVEST 中该积水类的面积碳，避免重复相加。
- PLUS 的四种默认情景为 ND、UD、EP、RE。情景参数应有本地规划、历史变化、修复工程或开采方案依据；没有本地桥接器时不猜测软件参数。

## 结果验收

每次交付运行 `validate_analysis_results`，并返回生成的报告。

- 土地利用：OA、F1、IoU、各类别 precision/recall/F1/IoU；没有独立样本时标记 `pending_validation`。
- PLUS：FoM、关键地类 F1/IoU、至少两个随机种子的 FoM 稳定性。
- 碳储量：流程输出与独立 InVEST 运行总量的一致性。
- 生态服务：标准化值范围、AHP CR、敏感性分析摘要。
- 地图：图层完整性、图例人工核验结果、空间范围和导出分辨率。

详情按需读取：分类在 `envi_classification/` 和 `deep_learning/`，预处理与制图在 `arcgis_steps/`，PLUS 在 `plus_model/`，碳储量在 `invest_carbon/`，生态服务在 `ecosystem_service/`。
