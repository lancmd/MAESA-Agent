# GDAL 批量栅格与矢量处理

本模块是 ArcGIS Pro 的批处理补充，适用于多矿区、多年份、服务器环境或需要可重复命令行流程的任务。单次桌面处理仍可使用 `arcgis_steps/`。

## 目录

1. 使用边界
2. 输入检查
3. 栅格对齐与裁剪
4. 拼接与 COG
5. 矢量转换
6. 批处理验收

## 1. 使用边界

| 场景 | 推荐工具 |
|---|---|
| 单矿区交互检查、制图 | ArcGIS Pro |
| 多年份重复投影和裁剪 | GDAL 命令或脚本 |
| 多维气候/遥感时间序列 | xarray/rioxarray + Dask |
| 大规模矢量筛选和空间连接 | DuckDB Spatial/PostGIS |
| 最终 PLUS/InVEST 输入复核 | ArcGIS Pro 或 GDAL 双重检查 |

不要为了“开源”而重写已经稳定的 ArcGIS 流程；只有批量性、可复现性或计算规模带来明显收益时再切换。

## 2. 输入检查

```powershell
gdalinfo input.tif
ogrinfo -al -so input.gpkg
```

检查 CRS、GeoTransform、范围、行列数、波段、数据类型、NoData、Scale/Offset 和统计值。没有可靠 CRS 的数据必须先确认真实坐标系，不能猜测后直接 `-s_srs`。

记录工具版本：

```powershell
gdalinfo --version
projinfo "<TARGET_CRS>"
```

## 3. 按主网格投影、对齐和裁剪

先从 master grid 读取目标 CRS、精确范围和像元大小，再替换占位参数：

```powershell
gdalwarp `
  -t_srs "<TARGET_CRS>" `
  -te <XMIN> <YMIN> <XMAX> <YMAX> `
  -tr <XRES> <YRES> `
  -tap `
  -r near `
  -srcnodata <SOURCE_NODATA> `
  -dstnodata <TARGET_NODATA> `
  -cutline aoi.gpkg `
  input_lulc.tif output_lulc_aligned.tif
```

规则：

- 土地利用、土壤、掩膜等分类数据使用 `near`，降分辨率时可在验证后使用 `mode`；
- DEM、气温、降水、反射率和密度使用 `bilinear`；
- 高分辨率连续数据聚合到粗网格可使用 `average`；
- 每像元人口/GDP 总量聚合可使用 `sum`，但必须核对总量守恒；
- `-tap` 只按目标分辨率调整坐标，并不自动复制任意 master grid 的原点；必须同时使用 master grid 的精确 `-te/-tr`，并比较输出 GeoTransform。
- 为保持与 master grid 相同的完整范围，使用 `-cutline` 掩膜但不加 `-crop_to_cutline`；若单独裁剪为边界外包矩形，才使用后者并在进入模型前重新对齐。

不要在同一数据上连续多次 warp。尽可能一次完成投影、重采样、范围和 NoData 设置。

## 4. 多景拼接与 COG

大量相邻影像先建立虚拟镶嵌，避免生成无必要的中间大文件：

```powershell
gdalbuildvrt mosaic.vrt tile_*.tif
gdalwarp -t_srs "<TARGET_CRS>" -tr <XRES> <YRES> -r bilinear mosaic.vrt mosaic_aligned.tif
```

归档或远程读取时转换为 Cloud Optimized GeoTIFF：

```powershell
gdal_translate -of COG -co COMPRESS=DEFLATE input.tif output_cog.tif
```

分类栅格的概览必须使用最近邻/众数语义，不能让概览产生新类别。COG 更适合归档和范围读取；若旧版 PLUS/InVEST 兼容性不明确，保留普通 GeoTIFF 工作副本。

## 5. 矢量格式与转换

新中间数据优先 GeoPackage；大型分析表可使用 GeoParquet。Shapefile 仅作遗留输入或必要交付。

```powershell
# 转换并投影到 GeoPackage
ogr2ogr -f GPKG -t_srs "<TARGET_CRS>" output.gpkg input.shp -nln features

# 按研究区范围预筛选
ogr2ogr -spat <XMIN> <YMIN> <XMAX> <YMAX> -spat_srs "<BBOX_CRS>" subset.gpkg input.gpkg
```

空间连接前断言两个图层 CRS 一致，并检查空几何、重复要素和无效几何。道路或河流数据用于距离栅格时，还要记录提取日期和要素筛选条件。

## 6. 批处理验收

每个输出必须与 master grid 比较：

- CRS 和坐标轴顺序；
- GeoTransform/像元原点；
- X/Y 分辨率；
- Bounds、Rows/Columns；
- 数据类型、NoData 和波段顺序；
- 分类值域或连续变量物理值域；
- 文件大小、校验值和处理日志。

对大栅格采用分块/惰性读取，不要把全国多期影像一次性转为内存数组。把最终命令、GDAL/PROJ 版本和输入输出校验值写入数据清单。
