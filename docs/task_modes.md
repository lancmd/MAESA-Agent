# 项目任务模式

`project.json` 的 `task_type` 让 MAESA 只验证、编译和运行当前目标所需的模块。手写项目可以省略该字段以兼容旧项目；使用 `build_local_project_from_inputs` 时建议显式填写。

| task_type | 启用模块 | 最小核心输入 |
|---|---|---|
| `classification_only` | ENVI、PyTorch 语义分割或已登记 ResNet-50 图块分类 | 一期或多期影像，加 ROI 或模型包 |
| `classification_invest` | 按期 ENVI/PyTorch 分类、独立精度评价、InVEST Carbon / Habitat Quality | 多期影像；每期自己的 ROI 和独立验证样本；碳密度表及所选 InVEST datastack |
| `lulc_change_analysis` | 30 m 对齐、转移矩阵和 Sankey | 至少两期已有 LULC |
| `plus_only` | PLUS ND/UD/EP/RE | 至少两期已有 LULC、驱动因子；RE 另需沉陷深度或 w.dat |
| `invest_only` | InVEST Carbon 或已配置生态模型 | 已有 LULC、对应碳密度表或模型 datastack |
| `ecosystem_service_only` | Min-Max/AHP、权衡和敏感性 | 指标表和生态服务配置 |
| `mapping_only` | ArcGIS Pro 布局 | APRX、布局和已有结果图层 |
| `full_chain` | 分类、PLUS、InVEST | 多期影像、分类样本/模型、驱动因子、碳密度和 RE 沉陷输入 |

最终布局可以引用工作流中尚未生成的结果，而不是把它伪装成输入文件：

```json
{
  "source": "stage_output",
  "stage_id": "invest_carbon_ND",
  "output_index": 0,
  "name": "自然发展情景碳储量",
  "kind": "continuous"
}
```

## 分类—InVEST 多期任务

`classification_invest` 面向“不做 PLUS、直接由多期影像得到 LULC、碳储量和生境质量”的研究。每个 `inputs.imagery_periods` 项目可带自己的 `training_roi`（也接受简写 `roi`）和 `accuracy` 对象；分类器、精度评价和 InVEST datastack 都按年份独立执行。ENVI 项目每一期都要显式给出训练 ROI；每一期也要给出不同的 `validation_samples` CSV、`x_field`、`y_field` 和 `samples_crs`。

精度阶段不读取 CSV 中预先填写的预测类别。它会从该年份刚生成的 LULC 栅格在验证点坐标处重新取样，并在报告中写入 `prediction_source: classification_raster_sample`。训练 ROI 与验证 CSV 不能是同一文件；如果训练 ROI 配置了角色字段，则其中只能保留训练角色，不能把验证样本一起交给 ENVI。

```json
{
  "year": 2020,
  "path": "data/landsat_2020.tif",
  "training_roi": "data/roi_2020.gpkg",
  "accuracy": {
    "validation_samples": "data/validation_2020.csv",
    "reference_field": "reference",
    "x_field": "x",
    "y_field": "y",
    "samples_crs": "EPSG:32650"
  }
}
```

未写 `output` 或 `confusion_matrix` 时，编译器分别生成 `outputs/validation/lulc_accuracy_<year>.json` 与 `outputs/validation/lulc_confusion_matrix_<year>.csv`，因此不会覆盖其他年份的 OA、F1、IoU 和混淆矩阵。

若要让 Habitat Quality 数据栈随每期 LULC 自动建立，在 `invest_models` 中为 `habitat_quality` 提供显式的 `datastack_builder`（JSON 配置路径或内联配置）。配置需包含威胁栅格、威胁距离/权重/衰减方式、各 LULC 类的生境适宜性与敏感性，以及半饱和常数；流程会为每个年份生成独立的数据栈、威胁表和敏感性表，而不是把某一期的 `lulc_cur_path` 套用于全部年份。

```json
{
  "habitat_quality": {
    "enabled": true,
    "datastack_builder": "data/habitat_quality_config.json",
    "service_unit": "index_0_to_1",
    "service_aggregation": "mean"
  }
}
```

仓库的真实六期验收测试不包含任何个人电脑路径。准备好已校验的本地项目后，仅设置 `MAESA_REAL_SIX_PERIOD_PROJECT` 为该 `project.json` 的路径，再运行 `tests/real_six_period_classification_invest.py`；未设置该变量时测试会在 CI 中跳过。

编译器会检查 `stage_id` 和 `output_index` 是否对应前序阶段的声明输出；工作流运行到布局阶段前再确认文件实际存在。也可用 `path_scope: "workspace"` 指向已在工作区内生成的成果。
