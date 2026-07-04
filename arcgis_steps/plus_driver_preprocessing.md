# ArcGIS Pro：PLUS 驱动因子预处理

本模块用于把来源、投影和分辨率不同的自然与社会经济数据处理为 PLUS 可读取的同网格单波段栅格。

## 目录

1. 建立主网格
2. 驱动因子类型与处理方法
3. DEM 派生坡度和坡向
4. 道路、水系等距离因子
5. 人口、GDP 和气候处理
6. NoData、输出与验收

## 1. 建立主网格

以 PLUS 基期土地利用图作为 master grid。先记录其 CRS、Cell Size、Extent、Rows/Columns、NoData 和类别编码，然后在所有工具的 Environments 中设置：

- Output Coordinate System：master grid；
- Processing Extent：master grid；
- Snap Raster：master grid；
- Cell Size：master grid；
- Mask：研究区边界。

驱动因子最终必须与基期土地利用图行列数、范围和像元原点一致。仅把所有文件“设成 30 m”并不足以保证对齐。

## 2. 驱动因子清单

| 因子 | 数据类型 | 推荐处理 | 备注 |
|---|---|---|---|
| DEM | 连续 | Project Raster + Bilinear | 先统一网格，再派生地形因子 |
| 坡度 | 连续 | 由对齐 DEM 派生 | 通常输出 Degree |
| 坡向 | 环状连续 | 由对齐 DEM 派生 | 平地为 -1；必要时转 northness/eastness |
| 土壤类型、地质类型 | 分类 | Nearest | 保持整数编码 |
| 气温、降水 | 连续 | Bilinear | 放大不代表增加细节 |
| 人口/GDP 密度 | 连续 | Bilinear | 确认单位为每 km² 等密度 |
| 人口/GDP 总量 | 每像元总量 | 守恒聚合或先转密度 | 不直接 Bilinear |
| 道路、铁路、河流、城镇、矿区 | 矢量源 | Distance Accumulation | 输出到最近源的距离 |
| 保护区、基本农田等约束 | 分类/二值 | Nearest | 与驱动因子分开管理 |

静态因子和动态因子应分开标记。DEM、坡度通常为静态；人口、GDP、夜间灯光和部分气候因子应记录对应年份，不得用“最新值”代替历史年份却不说明。

## 3. 只有 DEM 时生成坡度和坡向

先处理 DEM：

1. 检查水平坐标单位和高程 Z 单位；
2. 填补或解释研究区内部 NoData，不把空洞直接设为 0；
3. Project Raster 到目标 CRS，连续数据使用 Bilinear；
4. 设置 master grid 的 Snap Raster、Extent 和 Cell Size；
5. 使用对齐后的 DEM 生成地形因子。

推荐路径：`Spatial Analyst Tools → Surface → Surface Parameters`

该工具需要 Spatial Analyst 或 3D Analyst。

分别运行：

- Parameter Type = Slope；Slope Measurement = Degree；
- Parameter Type = Aspect；输出 0—360°，平坦区域通常为 -1；
- Z Unit：按 DEM 实际单位设置，不确定时先查元数据；
- Local Surface Type：一般使用默认 Quadratic；高分辨率噪声 DEM 可测试更大 Neighborhood Distance 或 Adaptive Neighborhood。

Surface Parameters 是当前推荐实现；若为复现实验必须匹配旧结果，才使用传统 Slope/Aspect 工具并记录算法差异。

坡向存在 0°/360°不连续。若模型对连续距离敏感，可使用 Raster Calculator 派生：

```text
northness = Cos(aspect * 0.0174532925199433)
eastness  = Sin(aspect * 0.0174532925199433)
```

平地 `aspect = -1` 应先设为 NoData 或按研究设计赋中性值，不能直接参与三角函数而不说明。

## 4. 生成距离因子

推荐路径：`Spatial Analyst Tools → Distance → Distance Accumulation`

该工具需要 Spatial Analyst。

步骤：

1. 将道路、铁路、河流、城镇边界、矿区边界等矢量投影到目标分析 CRS；
2. 修复空几何和明显拓扑错误，保留数据日期与来源；
3. 分别以每类要素作为 Input Raster or Feature Sources；
4. 不提供 Cost/Surface/Barrier 时生成普通最近直线距离；
5. 小区域投影坐标系可用 Planar；跨大区域可选择 Geodesic；
6. 显式设置 master grid 的输出坐标系、范围、像元大小和 Snap Raster；
7. 检查源位置是否为 0，距离是否随远离源而增大，单位是否为米。

若输入源是栅格，只有源像元应为有效值，非源像元必须为 NoData；0 也是有效源值，不能用“背景 0、源 1”的整幅有效栅格直接计算，否则所有像元都会被视为源。

常见输出：`road_distance.tif`、`railway_distance.tif`、`river_distance.tif`、`urban_distance.tif`、`mine_distance.tif`。

## 5. 人口、GDP 和气候

### 人口/GDP

- 先确认栅格表示密度、每像元人数/产值，还是行政区总量分配结果；
- 密度栅格可按连续变量处理，但应记录原始有效分辨率；
- 总量栅格降分辨率时使用求和聚合以守恒；需要更细网格时先除以实际像元面积转为密度，再对齐；
- 处理后核对研究区总人口或 GDP 是否出现非预期变化。

### 气候

- 统一温度单位（°C 或缩放整数）和降水单位（mm）；
- WorldClim 多年平均值属于气候背景，不能解释成某一年的气象值；
- TerraClimate 等时间序列应先按目标年份聚合，再空间对齐；
- 1 km 数据重采样到 30 m 后仍代表约 1 km 信息尺度，模型解释中必须注明。

## 6. NoData、输出与验收

- 研究区内部无合理原因的 NoData 会造成 PLUS 驱动因子缺口；先查来源，再选择邻域填补、辅助数据补齐或缩小共同有效区；
- 不要把 NoData 一律设为 0，因为 0 可能代表真实高程、距离或密度；
- 类别栅格使用整数，连续驱动因子可使用 Float32；
- 输出单波段 GeoTIFF，文件名使用 ASCII、下划线且无空格；
- 不在未确认当前 PLUS 版本要求时擅自归一化或改变因子方向；保留原始单位版和模型输入版；
- 新建矢量中间文件优先使用 File Geodatabase/GeoPackage，保留来源和许可信息。

最终逐文件验收：

| 检查项 | 合格标准 |
|---|---|
| CRS | 与基期土地利用图完全一致 |
| Cell Size | X/Y 与 master grid 一致 |
| Extent/Rows/Columns | 完全一致 |
| Snap | 像元边界重合 |
| NoData | 研究区内无未解释空洞 |
| 值域/单位 | 与因子物理意义一致 |
| 时间 | 与模拟基期或设计年份匹配 |
| 数据类型 | 分类为整数，连续量为合适浮点/整数 |

建立 `data_manifest.csv`，至少记录 `factor_name`、`source`、`source_date`、`source_crs`、`source_resolution`、`unit`、`tool`、`resampling`、`output_crs`、`output_cellsize`、`nodata` 和 `output_file`。这份清单是复现实验和排查 PLUS 报错的第一入口。
