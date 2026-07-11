# ArcGIS Pro 成果制图与布局输出

空间分析完成后，使用 `compose_layout` 将已经验证的结果写入 ArcGIS Pro 布局并导出。该操作面向可重复出图：保留原始 `.aprx`，在副本中添加成果图层、应用既有符号、更新标题和地图范围，再生成 PDF、PNG 与布局检查记录。

适合输出的成果包括土地利用分类、分类置信度、PLUS 情景预测与变化、碳储量及其变化、沉陷深度和沉陷积水碳储、生态服务单项与综合指数图。

## 1. 前置条件

准备一个 ArcGIS Pro `.aprx` 作为布局底图。它至少应包含：

- 指定名称的布局和目标地图；
- 用于显示成果的地图框；
- 可选的标题文本元素和图例元素；
- 与成果数据匹配的 `.lyrx` 图层文件（分类色带、连续色带、分级断点等）。

`compose_layout` 不修改源 `.aprx`，而是先保存一个输出副本。这样每次任务都有独立的制图工程和可追溯的导出结果。

## 2. `compose_layout` 操作

直接调用 ArcGIS 操作时，输入包含 `.aprx`、布局名称、成果图层和验证 JSON 的输出位置。每个 `layers` 项的 `path` 指向实际成果；如提供 `symbology_layer`，会引用对应的 `.lyrx` 应用符号系统。

```json
{
  "id": "compose_lulc_2025",
  "type": "compose_layout",
  "aprx": "project/base_layout.aprx",
  "aprx_output": "outputs/maps/lulc_2025_layout.aprx",
  "layout_name": "LandUseLayout",
  "map_name": "LandUseMap",
  "map_frame_name": "MainMapFrame",
  "title_element_name": "MapTitle",
  "title_text": "2025 年矿区土地利用分类",
  "legend_name": "MainLegend",
  "extent_from_layer": "土地利用分类",
  "layers": [
    {
      "path": "outputs/lulc/LULC_2025.tif",
      "name": "土地利用分类",
      "symbology_layer": "styles/lulc_7class.lyrx",
      "visible": true
    },
    {
      "path": "inputs/boundaries/mine_boundary.gpkg",
      "name": "矿区边界",
      "symbology_layer": "styles/mine_boundary.lyrx",
      "visible": true
    }
  ],
  "pdf": "outputs/maps/lulc_2025.pdf",
  "png": "outputs/maps/lulc_2025.png",
  "resolution": 300,
  "validation_output": "outputs/validation/lulc_2025_layout.json"
}
```

操作顺序如下：

1. 复制 `aprx` 到 `aprx_output`；
2. 打开指定布局和目标地图；
3. 向目标地图添加结果图层，必要时通过 `.lyrx` 应用符号；
4. 更新标题文本；
5. 若提供 `extent_from_layer`，以该图层更新指定地图框的范围；
6. 保存工程副本，导出 PDF 和/或 PNG；
7. 写出布局验证 JSON。

当通过 `local_project.json` 生成工作流时，`gis_outputs` 会编译为同类操作。建议将可公开复用的底图、图层文件和成果命名一并纳入项目目录；临时成果仍写入任务工作区。

## 3. 验证 JSON 与人工复核

`validation_output` 记录布局名称、目标地图、期望图层、实际图层、缺失图层、地图框范围、分辨率和导出文件路径。例如：

```json
{
  "layout": "LandUseLayout",
  "expected_layers": ["土地利用分类", "矿区边界"],
  "missing_layers": [],
  "legend_present": true,
  "legend_requires_visual_check": true,
  "resolution": 300
}
```

这份 JSON 可自动确认图层是否加入、导出是否完成，以及布局是否包含图例元素；它不能判断图例每一项的颜色、顺序、标签、断点或是否被遮挡。导出后仍应打开 PNG 或 PDF 进行视觉确认，至少检查：

- 图例类别、名称、颜色和单位是否与结果数据一致；
- 标题中的年份、情景和指标名称是否正确；
- 地图范围、比例尺、指北针和边界是否完整；
- 栅格 NoData 显示、连续色带方向和分类编码是否合理；
- PDF/PNG 分辨率是否满足交付要求。

如果布局缺少标题、图例或地图框元素，操作会保留可用部分或在需要指定元素时报告错误。应在底图工程中补齐元素后重新运行，而不是在导出的图像上手工拼接。

## 4. 图层与符号管理

- 分类栅格使用稳定的分类编码和 `.lyrx` 色表；不同年份、不同情景使用同一套编码时应复用同一符号文件。
- 连续栅格（碳储、沉陷深度、生态服务指数）在 `.lyrx` 中固定色带方向、最小/最大值和分级方式，避免自动拉伸造成跨图不可比。
- 边界、道路、水系等辅助要素应使用单独的 `.lyrx`，避免继承当前 ArcGIS 会话的临时符号。
- 同一布局若需要多幅地图，分别配置地图框和范围来源；不要用同一个范围覆盖所有专题图。

## 5. 交付内容

每次制图任务至少保留：

- 输入 `.aprx` 的只读版本及生成的 `.aprx` 副本；
- PDF 和/或 PNG；
- 对应 `validation_output` JSON；
- 使用的 `.lyrx`、数据版本、导出分辨率和人工视觉复核记录。

数值分析仍以原始 GeoTIFF、矢量结果和统计表为准。布局图用于传达成果，不替代土地利用、PLUS、InVEST 或生态服务结果的数值验证。
