# 水源供给与生境质量自动计算

本模块把每期 LULC 或 PLUS 情景 LULC 分别传入本地 InVEST Annual Water Yield 和 Habitat Quality。每次运行使用独立工作目录；输出随后进入情景比较、权衡分析、Min-Max 或 AHP 综合评价。

## 水源供给

Annual Water Yield 的像元值是年产水深度。项目汇总阶段会按像元面积把有效像元的 mm 转换为 m³；不能直接把水深像元值相加。

高潜水位采煤沉陷区可用沉陷积水进行校准：从遥感影像提取沉陷积水边界，以 PIM `w.dat` 生成的沉陷深度与 DEM 叠加得到沉陷后地形，按统一水面高程计算积水库容/径流体积，再与 InVEST 年产水量比较，选择误差可接受的季节常数 `Z`。校准记录应保存候选 Z、观测/反演体积、InVEST 体积、相对误差和选定值。

Annual Water Yield datastack 至少要包含：

- `lulc_path`：本工作流生成的 LULC；
- `precipitation_path`：对应年份年降水 GeoTIFF，mm；
- `eto_path`：对应年份参考蒸散 GeoTIFF，mm；
- `depth_to_root_rest_layer_path`：根系限制层深度 GeoTIFF，mm；
- `pawc_path`：植物可利用含水量 GeoTIFF，0–1；
- `watersheds_path`：流域/汇水区矢量；
- `biophysical_table_path`：至少含 `lucode`、`root_depth`、`Kc` 和 `lulc_veg`；
- `seasonality_constant`：经校准或有明确依据的正数 Z。

同一年内，降水、ET0、LULC、土壤层和流域应统一到同一投影、范围、像元网格。若水文计算涉及面积或体积，使用米制投影坐标系。

## 生境质量

Habitat Quality 以 LULC 的生境适宜性、威胁源影响和各地类对威胁的敏感性计算 0–1 指数。项目会把每期/每情景栅格按有效像元做面积加权平均；空间评价仍保留原始生境质量栅格。

Habitat Quality datastack 至少要包含：

- `lulc_cur_path`：本工作流生成的 LULC；
- `threats_table_path`：至少含 `threat`、`max_dist`、`weight`、`decay`、`cur_path`；
- 每个 `cur_path` 指向同一时期的威胁栅格，例如建设用地、道路、铁路、采场/排土场或夜间灯光；
- `sensitivity_table_path`：至少含 `lulc`、`habitat`，并为 threats 表每个威胁提供敏感性列；
- `half_saturation_constant`：有明确生态学依据的正数；
- 可选 `access_vector_path`：保护地或可达性修正面。

每个威胁栅格的年份、距离单位和衰减类型都要记录。威胁范围不是由道路距离栅格自动推断的；需要提供威胁源栅格或原始矢量，以及研究者确认的最大影响距离、权重和敏感性。

## 自动检查与输出

运行非 Carbon InVEST 前，`invest_ecosystem_contract.py` 会检查 datastack、参数表关键字段和本地文件是否存在。检查不通过时流程停止，不产生伪造的水源供给或生境质量图。

输出包括：

- 各期/各情景 Annual Water Yield 栅格与 m³ 汇总；
- 各期/各情景 Habitat Quality 栅格与平均指数；
- 校准记录（若启用沉陷积水校准）；
- 水源供给、生境质量、碳储量的权衡/协同与综合生态服务结果；
- 自动 SVG 专题图，以及可选 ArcGIS Pro 布局图。

## Habitat Quality 数据栈构建器

不再要求先手工编辑 Habitat Quality datastack。可调用 MCP
`build_habitat_quality_datastack`，或运行
`scripts/invest_datastack_builder.py --config habitat_config.json --output-dir <workspace>`。
构建器会写出独立的 `habitat_threats.csv`、`habitat_sensitivity.csv`、
`habitat_quality_datastack.json` 和 `habitat_datastack_manifest.json`；每个年份或 PLUS 情景应使用自己的输出目录。

配置文件仍由研究者提供生态参数，例如：

```json
{
  "lulc_path": "data/LULC_2025.tif",
  "half_saturation_constant": 0.5,
  "threats": [
    {"name": "road", "raster": "data/road_2025.tif", "max_distance_m": 1000, "weight": 1, "decay": "linear"}
  ],
  "sensitivity": [
    {"lulc": 1, "habitat": 0.8, "threats": {"road": 0.3}}
  ]
}
```

构建时会检查威胁栅格与 LULC 的 CRS、范围、分辨率和像元网格是否一致；敏感性表必须覆盖该期 LULC 的全部有效类别。表中多出的类别会记录为警告，缺失类别或 0–1 范围以外的适宜性/敏感性会阻止运行。构建器不会根据影像猜测威胁权重、影响距离或敏感性。

在 `project.json` 中可将上述 JSON 文件写为 `invest.models.habitat_quality.datastack_builder`。工作流会在每期分类图或每个 PLUS 情景图生成后覆盖其中的 `lulc_path`，并在各自的 `generated/invest_habitat_quality_<时期>_habitat/` 目录中构建独立数据栈；因此共享参数文件可以不写 `lulc_path`。

已有生成表或数据栈时，命令行需显式传入 `--confirm-overwrite`，MCP 需传入 `confirm_overwrite: true`；这不会修改原始 LULC、威胁或敏感性输入。
