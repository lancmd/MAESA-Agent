---
name: mining-area-ecological-space-analysis
description: 使用用户本地遥感影像、ROI、矿区边界、碳密度、驱动因子和沉陷数据，直接调用 PyTorch/ENVI、ArcGIS Pro、PLUS、InVEST 与开放 GIS 后端，执行矿区土地利用、沉陷积水碳储和生态服务分析；用于需要真实产物、日志和验证结果的矿区 GIS 任务。
---

# 矿区生态空间分析执行智能体

## 核心约束

本 Skill 的默认交付物是实际生成的数据、模型结果、日志和验证报告，不是操作步骤。只要本机或已连接服务具备能力，就直接运行；不要把可执行工作改写成“请用户自行在软件中操作”。

必须遵守：

- 先调用 MCP `list_backends` 与 `backend_capabilities`，再检查用户数据、坐标参考、像元类型和分类编码；不得先假设软件安装路径。
- 每项工作写入任务清单，并在独立工作目录保存状态与日志；失败后从未完成阶段继续。
- 离散分类栅格只用最近邻重采样，连续因子通常用双线性；所有 PLUS/InVEST 输入对齐同一主网格。
- 不伪造缺失数据、精度、碳密度、PLUS 参数或软件命令行参数。
- 没有独立验证样本时将分类精度标为 `pending`，继续其他可执行阶段。
- 只有缺少必要输入、许可、身份认证，或软件没有可验证的自动化接口时才暂停对应阶段；其他阶段继续。
- PLUS 默认情景固定为 ND（自然发展）、UD（城镇发展）、EP（生态保护）和 RE（资源开采）。RE 只接收外部沉陷预计软件产生的 `w.dat`、`w.txt` 或栅格；必须先转为米单位、正值向下、对齐主网格的沉陷深度 TIF，作为核心驱动并与其他因子共同运行，本项目不计算概率积分法下沉值。

## 每次任务的执行顺序

1. 优先接收用户本地项目包：遥感影像、ROI、矿区边界、碳密度、PLUS 驱动因子，以及可选训练 ROI、PyTorch 模型、DEM、`w.dat`/沉陷深度和生态服务指标表。使用 `templates/local_project.json` 建立清单，并运行 `project_validator.py`。
2. 调用矿区 GIS MCP 的 `list_backends`，对目标后端调用 `backend_capabilities`。后端可来自桌面软件插件、HTTP 服务、socket 桥接器或本地命令适配器。
3. 根据任务调用明确工具：PyTorch 模型先用 `validate_lulc_model` 再用 `run_pytorch_lulc`；ENVI 用 `run_envi_classification`；PLUS 用 `run_plus_scenario`；ArcGIS 用 `run_arcgis_operations`；InVEST 用 `run_invest_carbon` 或 `run_invest_ecosystem_model`。
4. 异步任务收到 `job_id` 后持续调用 `get_job_status`，完成后调用 `list_job_outputs`；不得把 `accepted`、`running` 或 `prepared` 报告成完成。
5. MCP 后端不可用但当前环境允许本地执行时，复制并填写 `templates/workflow_job.json`，再使用本地兜底：

   ```powershell
   python scripts/workflow_agent.py probe --output <工作目录>/software_probe.json
   ```

6. 运行预检和计划：

   ```powershell
   python scripts/workflow_agent.py plan --job <任务清单.json>
   ```

7. 执行全部阶段或指定阶段：

   ```powershell
   python scripts/workflow_agent.py run --job <任务清单.json>
   python scripts/workflow_agent.py run --job <任务清单.json> --stage <阶段ID>
   ```

8. 检查 MCP 响应或工作目录中的状态、日志和声明输出。对栅格至少检查 CRS、分辨率、范围、行列数、NoData、值域和主网格对齐。
9. 向用户返回实际产物、未完成阶段及其唯一阻塞原因。不要用长篇教程代替执行结果。

## 软件路由

| 任务 | 首选执行后端 | 自动化方式 |
|---|---|---|
| 用户本地遥感影像 | ENVI / PyTorch | 直接按模型包或 ROI 进入分类阶段 |
| 投影、重采样、裁剪、坡度坡向、距离、面积和转移矩阵 | ArcGIS Pro/QGIS | MCP → 软件内插件或远程处理服务；本地 ArcPy 是可选后端 |
| 监督分类 | ENVI | MCP → ENVI Task/IDL 桥接器；许可不可用时记录阻塞 |
| 深度学习分类 | PyTorch | MCP → 模型包校验、分块推理、置信度栅格；规范见 `deep_learning/pytorch_workflow.md` |
| 情景模拟 | PLUS | MCP → 对应版本的 PLUS 插件/桥接器；未知版本不得猜测参数 |
| 碳储量 | InVEST | MCP → InVEST 服务或命令适配器 |
| 等价的开放 GIS 处理 | GDAL/QGIS/GeoPandas/rioxarray | 仅在语义、像元对齐和输出类型等价时替代商业软件 |

协议见 `interfaces/backend_protocol.md`，后端注册表示例见 `interfaces/backend_registry.example.json`。详细适配器边界见 `execution/software_adapters.md`，任务状态规则见 `execution/execution_contract.md`。

## 领域判定

- 分类体系、矿区类型和数据源：读取 `config/`。
- ENVI 分类器、ROI 和精度：读取 `envi_classification/`。
- ArcGIS 与 PLUS 驱动因子处理：读取 `arcgis_steps/`。
- PLUS 校准、转换矩阵与情景：读取 `plus_model/`。
- InVEST 与沉陷积水复合碳库：读取 `invest_carbon/`。
- 开放数据、GDAL 和交付验证：读取 `open_gis_workflows/`。

这些文档是智能体的决策依据，不是默认输出。

## 关键输入边界

- InVEST 的 `lucode` 必须与土地利用栅格像元值一致；碳密度由用户提供并记录来源与单位。
- 沉陷积水不能只靠 NDWI/MNDWI 自动判定，需结合沉陷范围、历史影像、地形低洼区和人工判读。
- 用户选择 `subsidence_water.mode = thesis_4_3_composite` 时，必须调用 ArcGIS 的 `subsidence_water_carbon` 操作：以遥感积水边界、预采 DEM、正下沉深度和同一垂直基准水面高程计算库容，再计算水体、水生植被和底泥碳；该复合碳库替换 InVEST 的沉陷积水面积碳，不与其叠加。
- 面积统计使用投影坐标系或等面积投影，不在 EPSG:4326/Web Mercator 上直接计算平面面积。
- PLUS 未来预测前必须完成已知年份回代；Kappa 不能单独作为通过依据，应同时报告 FoM、关键地类精度和多随机种子稳定性。
- 生态服务综合评价默认使用碳储量、年水源供给和生境质量。情景间必须使用共同的标准化范围；AHP 必须通过一致性检验；水源供给校准只允许比较时间尺度与空间范围一致的水量。
- 对用户数据只在任务工作目录产生派生文件，不覆盖源数据，除非用户明确要求。

## 交付结构

每个任务工作目录至少包含：

```text
<workspace>/
├── agent_state.json
├── software_probe.json
├── logs/
├── generated/
├── intermediate/
├── outputs/
└── validation/
```

最终说明应区分 `completed`、`prepared`、`waiting_interactive`、`pending_validation` 和 `failed`，并链接实际生成文件。
