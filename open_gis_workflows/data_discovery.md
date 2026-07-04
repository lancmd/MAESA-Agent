# 开放地理数据发现与版本固定

本模块用于在 GEE 数据不足、需要批量下载或需要可追溯数据来源时，补充开放数据发现流程。它不替代 `config/data_sources.md`，而是规定“如何找到并固定具体数据版本”。

## 1. 发现顺序

按以下顺序寻找数据：

1. 用户提供或政府发布的矿区边界、工作面、沉陷和修复工程数据；
2. 官方卫星/地形数据目录及 STAC API；
3. 国家或省级自然资源、气象、人口和基础地理数据平台；
4. OpenStreetMap 等开放矢量数据；
5. 全球通用替代数据，如 WorldPop、GHSL、Copernicus DEM、WorldClim；
6. 无合适来源时，才采用人工下载或自行解译。

矿区专有数据优先级高于全球通用数据。全球道路或人口栅格不能自动视为真实矿区生产资料。

## 2. STAC 用途

STAC 用统一结构描述带时间和空间范围的影像、DEM 等资产。适合：

- 按矿区范围、年份和云量搜索 Landsat/Sentinel；
- 在下载前读取波段、投影、分辨率、处理级别和许可；
- 保存具体 Item ID，而不是只记录“使用 Sentinel-2”；
- 只读取研究区需要的 COG 范围，减少整景下载。

常见目录包括 Microsoft Planetary Computer、Element 84 Earth Search、Copernicus Data Space 和 USGS LandsatLook。使用前核对目录的集合 ID、更新时间、访问条款和资产命名，不要把示例 URL 永久写死。

## 3. 搜索记录

每次检索至少记录：

| 字段 | 示例含义 |
|---|---|
| `aoi_id` | 矿区唯一编号 |
| `bbox`/geometry | 实际搜索范围 |
| `datetime` | 起止日期 |
| `collection` | 数据集合 ID |
| `cloud_filter` | 云量条件 |
| `item_ids` | 最终使用的场景 ID |
| `asset_keys` | 使用的波段或文件 |
| `processing_level` | L2A、Level-2 等 |
| `accessed_at` | 检索日期 |
| `license` | 许可与署名要求 |

不要只保存动态查询条件。上游集合会增加或重处理影像，相同查询在未来可能返回不同结果。

## 4. 数据源补充规则

- DEM：除 SRTM 外，可比较 Copernicus DEM GLO-30；高精度研究优先当地测绘或 LiDAR DTM；
- 人口：WorldPop 与 GHSL 均需记录年份、含义（人数或密度）和原始分辨率；
- 道路/铁路/水系：优先权威基础地理数据；缺失时使用 OSM，并记录提取日期；
- 气候：多年背景与逐年数据分开，ERA5-Land/TerraClimate 不应与 WorldClim 基准期混写；
- 土地覆盖参考：ESA WorldCover 等只能作为辅助或验证来源，必须先映射类别体系；
- 采矿和沉陷资料：记录数据管理部门、有效期、空间精度和保密限制。

## 5. OGC 服务注意事项

使用 WMS/WFS/WMTS 前先读取 GetCapabilities，记录服务地址、图层名、CRS、时间维、分页限制和许可。

- WMS 1.3.0 的 EPSG:4326 可能使用纬度/经度顺序；
- `CRS:84` 通常使用经度/纬度顺序；
- WFS 大数据需分页，不要假定一次返回全部要素；
- WMTS 必须读取 Tile Matrix Set，不要默认都是 EPSG:3857。

先用已知小范围做抽样请求，再进行全国或多矿区批量获取。

## 6. 交付要求

将最终来源写入 `templates/data_manifest.json` 的 `sources` 数组。至少固定场景/产品 ID、下载日期、来源 URL、许可、原始 CRS、原始分辨率和校验值。公开成果中保留 Sentinel/Copernicus、OSM、政府数据等要求的署名。
