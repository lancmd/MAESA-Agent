# ArcGIS Pro：将外部 w.dat / w.txt 接入 PLUS

本流程只把沉陷预计软件已经输出的规则网格 `w.dat`、`w.txt` 或 CSV 转换并对齐为 PLUS 驱动栅格，不计算 PIM、不插值预计沉陷，也不生成沉陷等值线。

## 1. 输入审计

确认文件至少包含 `X`、`Y`、`W`，或同时附带原点、行列数、网格间距和排列顺序。记录：

- 坐标系和水平坐标单位；
- W 的物理含义、单位和正负号约定；
- 预计年份、工作面 ID 和计算方案；
- 外部软件名称、版本和导出日期；
- 规则网格间距及点的排列方式。

若只有一列 W 且没有可靠的空间定义，应停止处理并由外部软件重新导出。本项目不根据点序号猜测坐标。

## 2. 表格检查

导入前检查：

- X/Y 是否落在研究区附近；
- X/Y 唯一组合是否有重复；
- 点数是否等于预期行数乘列数；
- 相邻坐标差是否符合声明的规则间距；
- W 是否存在空值、文本值或异常数量级。

不要修改原始文件；另存标准化副本，并记录所有字段映射。

## 3. 导入规则网格点

ArcGIS Pro 路径：`Analysis → Tools → XY Table To Point`。

- X Field：`X`；
- Y Field：`Y`；
- Coordinate System：输入坐标的真实 CRS，不是当前地图 CRS；
- 输出优先使用 File Geodatabase，也可使用 GeoPackage 交换。

导入后叠加矿区边界和工作面检查位置。位置错误时排查经纬度顺序、投影带号、假东移、坐标单位和 CRS，不能用“定义投影”强行移动数据。

## 4. 统一深度字段

根据外部软件文档确认 W 的单位和符号后，可新增 Double 字段 `DEPTH_MM` 统一单位。例如：

- W 为负值且单位 mm：`DEPTH_MM = -W`；
- W 为正值且单位 mm：`DEPTH_MM = W`；
- W 为 m：按已确认的符号处理后乘 1000。

不要无条件使用 `Abs(W)`，也不要凭经验反转符号。

## 5. 规则点转栅格

使用 `Conversion Tools → To Raster → Point to Raster`：

- Value field：`DEPTH_MM`；
- Cell size：使用外部文件声明的原始网格间距；
- 输出范围：使用外部结果实际覆盖范围；
- 输出：`subsidence_depth_raw.tif`。

这一步只是规则网格格式转换。若点并非规则网格，不在本流程中使用 IDW、Kriging、Natural Neighbor 等方法预计新值，应返回外部沉陷软件重新导出规则网格或栅格结果。

## 6. 对齐 PLUS 主网格

按 `arcgis_steps/projection_resample.md` 和 `arcgis_steps/plus_driver_preprocessing.md` 处理：

- Output Coordinate System、Extent、Snap Raster 和 Cell Size 使用基期土地利用图；
- 连续沉陷深度重采样通常使用 Bilinear；
- 研究区外设 NoData，零下沉与 NoData 必须区分；
- 输出 `subsidence_depth_aligned.tif`；
- 检查 CRS、像元大小、行列数、范围和像元原点。

重采样只服务于 PLUS 网格匹配，不能被描述为重新进行了沉陷预计。

## 7. 输出验收

- 原始点数与导入点数一致；
- 规则网格范围和间距与外部软件报告一致；
- 抽查原始点处的栅格值，量级和符号一致；
- 对齐前后记录最小值、最大值和均值；
- 最终栅格与 PLUS master grid 完全一致；
- 输出清单中不包含本项目生成的沉陷等值线或预测云图。

正式输出仅包括标准化点数据、`subsidence_depth_raw.tif`、`subsidence_depth_aligned.tif` 和处理日志。
