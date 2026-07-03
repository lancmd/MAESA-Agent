# ENVI 分类结果导出到 ArcGIS Pro

本文件规定分类栅格从 ENVI 进入 ArcGIS Pro、PLUS 和 InVEST 前的输出与检查规则。

## 1. 选择正确结果

最终导出对象必须是单波段 `Classification Raster`：像元值代表土地利用类别编码。

- Rule Raster：每类一个波段，存储概率、距离或判别值，不是最终分类图；
- Probability Raster：表示概率或置信度，不是类别编码；
- RGB 显示图：只保存渲染颜色，不能替代分类值。

## 2. ENVI 保存

可在 Classification Workflow 的 Export 面板启用 `Export Classification Image`，也可对最终栅格使用 Save Raster As/Export Raster to TIFF。推荐：

- 工作中间文件：ENVI Standard（`.dat + .hdr`）；
- GIS 交换文件：GeoTIFF（`.tif`）；
- 数据类型：能够容纳类别编码的整型，通常 Byte 即可；
- 投影、范围、像元大小和 NoData：保持明确且与原始分类网格一致；
- 不应用显示拉伸，不转成三波段 RGB。

分类颜色表可能不会被 ArcGIS Pro 完整继承，因此必须同时保留类别编码表。

## 3. ArcGIS Pro 检查

添加 GeoTIFF 后逐项核对：

1. 图层属性中的坐标系、范围、行列数和像元大小；
2. 唯一值是否仅包含预期的 1—6 或 1—7，以及约定的 NoData/0；
3. 与研究区边界和原始影像叠加是否对齐；
4. 多期分类图是否具有相同投影、像元大小、范围、Snap Raster 和编码；
5. 抽查沉陷水面、道路、采场和边界小斑块是否在导出时丢失。

显示全黑通常只是符号化问题：使用 `Symbology → Unique Values`，字段选 `Value`。构建属性表时使用：

`Data Management Tools → Raster → Raster Properties → Build Raster Attribute Table`

该工具要求单波段整型分类栅格；若输入为浮点概率图，先回 ENVI 确认是否导错结果。

## 4. NoData 与 0 类

不要默认 0 一定是 NoData。先核对分类器和导出设置：

- 若 0 表示背景/未分类，保留原始图并另存分析副本；
- 转为 NoData 可使用 `Set Null`，表达式示例：`VALUE = 0`；
- 若研究需要统计未分类比例，不要提前删除 0；
- 不要把真实类别编码为 NoData。

出现 0—60 等大量连续值时，优先怀疑导出了 Rule/Probability Raster 或浮点结果，而不是土地利用分类图。

## 5. 类别编码与颜色

| 六类编码 | 地类 | 建议颜色 |
|---|---|---|
| 1 | 水体 | 蓝色 |
| 2 | 建设用地 | 红色 |
| 3 | 耕地 | 黄色 |
| 4 | 林地 | 深绿色 |
| 5 | 草地 | 浅绿色 |
| 6 | 裸地/工矿用地 | 灰色或棕色 |

七类体系按 `config/landuse_classes.md` 使用：1 沉陷积水、2 自然水体、3 建设用地、4 耕地、5 林地、6 草地、7 裸地/工矿用地。

## 6. 命名与交付

推荐文件名：`LULC_<year>_<sensor>_<method>.tif`，例如 `LULC_2025_S2_RF.tif`。最终交付包括：

- 原始分类图和后处理分类图；
- 类别编码/颜色表；
- 投影、分辨率、NoData 和分类方法说明；
- 精度报告与 ROI 版本；
- 多期分析所用的统一网格参数。

只有通过上述检查的整型分类栅格，才能继续用于面积统计、转移矩阵、PLUS、InVEST 和生态服务评价。
