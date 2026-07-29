# InVEST、沉陷积水与生态服务

## Carbon

Carbon 模型使用 LULC 和碳密度表。`lucode` 必须覆盖栅格所有有效类别；四个碳库为 `c_above`、`c_below`、`c_soil`、`c_dead`，单位统一为 Mg C/ha。历史各期和 PLUS 的 ND/UD/EP/RE 分别运行、分别保存，再汇总变化表和趋势图。

高潜水位矿区可对沉陷积水执行增强核算：水体碳、水生植被碳、底泥碳和库容都应有明确数据来源与不确定性。增强值替换标准 InVEST 中对应水体像元的碳量，不能重复叠加。

## Water Yield 与 Habitat Quality

Annual Water Yield 需要降水、ET0、土壤层、流域和生物物理表；Habitat Quality 需要 LULC、威胁表、威胁栅格和敏感性表。数据栈构建器会检查表字段、LULC 编码、威胁栅格及主网格一致性。NoData 不参与统计，也不能被解释为低服务值。

## 综合评价

服务指标可使用 Min-Max 或 AHP。输出需包含标准化范围、AHP 一致性比率、敏感性分析、情景比较、协同/权衡；GeoDetector 使用真实空间单元，不能把全区汇总值伪装为样本。
