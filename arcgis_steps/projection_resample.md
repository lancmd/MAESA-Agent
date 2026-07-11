# ArcGIS Pro 栅格投影、重采样与裁剪流程

本模块用于统一土地利用分类图、PLUS 驱动因子和 InVEST 输入数据的坐标系、像元网格、范围与 NoData。界面路径以 ArcGIS Pro 3.x 为参考。

## 目录

1. 统一目标
2. 选择分析坐标系与基准栅格
3. 定义投影和投影栅格
4. 重采样规则
5. 环境设置与裁剪
6. 推荐处理顺序
7. 质量检查

## 1. 统一目标

进入栅格叠加、转移矩阵、PLUS 或 InVEST 前，至少统一：

- 水平坐标系和必要的地理变换；
- 像元宽度、高度和单位；
- 左上角/左下角网格原点与像元对齐；
- 空间范围、行列数和研究区掩膜；
- NoData 语义与分类编码；
- 文件格式、数据类型和波段数。

坐标系相同不代表网格已经对齐；像元大小相同也不代表像元边界重合。

## 2. 选择分析坐标系与基准栅格

### 2.1 坐标系

- EPSG:4326 可用于交换和显示，但经纬度单位为度，不应直接用于平面面积、缓冲区和距离计算；
- EPSG:3857 适合网络地图显示，不是等面积投影，不应用于严肃面积统计；
- 单个或相邻矿区优先选择覆盖研究区的 CGCS2000 高斯—克吕格、合适 UTM 分区或其他当地投影；
- 跨省或全国面积统计应选择适合研究范围的等面积投影，并记录中央经线、标准纬线和基准面；
- 输入数据基准面不同时，在 Project Raster 中明确选择适用的 Geographic Transformation，不要仅凭图层“看起来重合”。

### 2.2 基准栅格

选定一幅最终土地利用分类图作为 master grid，记录：

- 坐标系；
- Cell Size X/Y；
- Extent；
- Width/Height（列数/行数）；
- NoData；
- 左上角或左下角坐标。

PLUS、InVEST 和多期转移分析均优先以最终土地利用图作为 Snap Raster。不要在处理不同因子时反复更换基准栅格。

## 3. 定义投影和投影栅格

### 3.1 Define Projection

路径：`Data Management Tools → Projections and Transformations → Define Projection`

该工具只写入/修正坐标系标签，不改变坐标值。仅在数据缺少或写错空间参考、且你能确认真实坐标系时使用。不能用它把 WGS 84 数据“变成”CGCS2000 或 UTM。

### 3.2 Project Raster

路径：`Data Management Tools → Projections and Transformations → Raster → Project Raster`

该工具真正转换栅格坐标。设置：

- Output Coordinate System：目标分析坐标系；
- Geographic Transformation：基准面不同时选择适用变换；
- Output Cell Size：与 master grid 一致；
- Resampling Technique：依据数据语义选择；
- Environments：设置 Snap Raster、Extent 和 Cell Size。

尽量在一次 Project Raster 中完成投影和目标像元设置，避免连续多次重采样造成信息损失。

## 4. 重采样规则

路径：`Data Management Tools → Raster → Raster Processing → Resample`

| 数据语义 | 推荐方法 | 说明 |
|---|---|---|
| 土地利用、土壤类型、行政编码 | Nearest | 保留整数类别值；土地利用不使用 Bilinear/Cubic |
| DEM、坡度、温度、降水、人口密度、GDP 密度 | Bilinear | 连续变量常用；Cubic 可能过冲，需检查异常值 |
| 影像反射率和连续指数 | Bilinear | 用于连续表面；分类前保持各波段同网格 |
| 人口总数、GDP 总量等每像元总量 | 不能直接 Bilinear | 由细网格变粗时 Aggregate/Sum；由粗网格变细时先转密度并说明分配假设 |
| 二值约束区、保护区类别 | Nearest | 避免生成 0—1 之间的伪类别 |

粗分辨率气候数据重采样到 30 m 只会改变网格，不会增加真实空间信息。分析说明应保留原始有效分辨率。

## 5. 环境设置与裁剪

在每个会产生栅格的工具中打开 `Environments`，显式设置：

- Output Coordinate System：目标分析坐标系；
- Processing Extent：master grid；
- Snap Raster：master grid；
- Cell Size：Same as layer/master grid；
- Mask：研究区边界或已栅格化掩膜；
- Geographic Transformations：需要时设置。

Snap Raster 会调整输出范围的像元角点；调整后的范围可能略大于原范围，这是保证边界像元被包含的正常现象。

裁剪路径：`Spatial Analyst Tools → Extraction → Extract by Mask`

该工具需要 Spatial Analyst。若输入与掩膜的像元大小或对齐不同，Extract by Mask 可能内部重采样。建议先投影、重采样并锁定环境，再裁剪。要素掩膜会按输入栅格网格内部栅格化，边界采用像元中心判定。

## 6. 推荐处理顺序

1. 盘点每个数据的来源、日期、单位、类型、坐标系、分辨率和 NoData；
2. 确认 Unknown 数据的真实坐标系，必要时 Define Projection；
3. 选定分析坐标系和 master grid；
4. 对矢量和栅格执行真正的投影转换；
5. 按数据语义重采样到目标像元大小；
6. 设置 Snap Raster、Extent、Cell Size 和 Mask；
7. 按研究区裁剪，输出单波段 GeoTIFF；
8. 对分类栅格重建属性表并检查编码；
9. 保存 `data_manifest.csv`，记录输入、输出、工具、参数和日期。

新建矢量中间数据优先使用 File Geodatabase 或 GeoPackage。Shapefile 仅用于遗留兼容，避免其字段名截断、编码和多文件管理问题。

## 7. 质量检查

完成后逐一检查：

- 所有输出的 CRS、Cell Size、Extent、Rows/Columns 是否一致；
- 叠加网格线后像元边界是否完全重合；
- 分类值是否仍只包含合法编码；
- 连续因子是否出现插值过冲、条带、空洞或异常块状；
- NoData 是否被错误填成 0，或 0 是否被错误当作 NoData；
- 人口/GDP 总量在聚合前后是否守恒；
- 输出是否为预期单波段、数据类型和单位；
- 文件名是否使用稳定的 ASCII 名称且无空格，便于 PLUS 读取。

建议命名：`LULC_2025_aligned.tif`、`dem_aligned.tif`、`population_density_aligned.tif`。归档可使用 Cloud Optimized GeoTIFF；若模型版本兼容性不确定，同时保留普通 GeoTIFF 工作副本。
