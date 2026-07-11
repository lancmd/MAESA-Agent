# 生态系统服务执行模块

本模块按“单项服务建模—统一量纲—综合评价—协同权衡—情景比较—空间归因”的顺序执行。默认服务是碳储量、年水源供给和生境质量；权重、阈值、威胁因子和情景参数由项目数据决定，模块不内置示例数值。

## 1. 单项服务

- 碳储量：调用 InVEST Carbon；高潜水位煤矿区可按 `invest_carbon/subsidence_water_carbon.md` 用沉陷积水复合碳库替换 InVEST 的沉陷积水面积碳。
- 年水源供给：调用当前 InVEST 的 `annual_water_yield` 模型。输入 LULC、降水、参考蒸散、植物蒸散系数、土壤有效持水量和用户校准的季节性参数；模型结果必须注明年份和单位。
- 生境质量：调用当前 InVEST 的 `habitat_quality` 模型。输入 LULC、威胁因子栅格/矢量、威胁距离与权重、土地利用敏感性表和可访问性约束。

三项结果进入融合前必须具有同一研究范围、投影、像元网格或同一分区统计单元。碳储量用 `t C`、年水源供给用 `m³/年`、生境质量为无量纲值；不得直接相加。

## 2. 年水源供给校准

沉陷积水区可用“遥感积水边界 + PIM 下沉地形 + DEM + 水面高程”得到的独立水量结果，校准年水源供给模型的候选季节性参数。候选表必须含参数值和该参数下的模型水量，调用 `calibrate_annual_water_yield` 选择绝对误差最小的候选值。

仅当两者都是同一空间范围、同一时间尺度的可比较水量时才允许校准。静态库容不是年度产水量，不能在没有补给、排泄和时间尺度转换依据时直接代替年水源供给。

## 3. 综合生态系统服务指数

`ecosystem_service.py` 先对每个指标进行 Min-Max 标准化，再作加权线性组合：

```text
benefit_score = (x - min) / (max - min)
cost_score    = (max - x) / (max - min)
composite     = Σ(weight_i × score_i)
```

常数指标的得分为 `0.5`，表示它不区分空间单元。Min-Max 模式必须提供用户权重；AHP 模式必须提供互反成对比较矩阵并通过一致性比率检验。默认要求 `CR <= 0.10`。

情景或多期对比必须把所有待比较行放在同一张指标表中标准化，或在配置中写入共同的 `normalization.bounds`。分别对每个情景独立归一化后，不得比较其综合分数。

## 4. 协同、权衡和影响因素

- 调用 `analyze_ecosystem_tradeoffs` 对服务指标进行 Spearman 秩相关分析；正相关标为协同，负相关标为权衡，常数指标标为未定义。结果不自动声称具有统计显著性。
- 调用 `analyze_ecosystem_drivers` 计算 GeoDetector 因子 q 值与双因子交互 q 值。连续因子必须先按用户记录的分级方案离散化；输出不附带 p 值，显著性检验需另行指定方法。
- 因子可包含土地利用、降水、蒸散发、高程、坡度以及其他具有空间和时间依据的变量；不得把未验证的解释变量当作因果结论。

## 5. 情景比较

先对 ND、UD、EP、RE 或生态治理/自然演化等情景分别运行三项服务，再通过 `compare_ecosystem_scenarios` 以用户指定的参考情景汇总平均值和差值。比较表必须保留 `scenario` 字段；解释时应说明土地利用、约束、驱动因子和治理范围的差异。

## 6. 运行接口与图件

- InVEST：MCP `run_invest_ecosystem_model`，模型仅允许 `annual_water_yield`、`habitat_quality` 或 `carbon`；参数通过用户准备的当前版本 datastack 传入。
- 综合评分：MCP `evaluate_ecosystem_services`。
- 校准、权衡、情景比较、GeoDetector：对应的 MCP 生态服务工具。
- 将分区/网格评分表连接回 ArcGIS Pro 图层，或将同网格结果转栅格；输出三项服务图、综合指数图、变化图、情景差异图、权衡表和归因表，再用 `export_layout` 导出 PDF/PNG。
