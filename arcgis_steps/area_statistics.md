# ArcGIS Pro 土地利用面积统计流程

本模块用于统计矿区土地利用分类图的各类面积、比例及分区面积。

## 目录

1. 输入检查
2. 属性表法
3. Tabulate Area 法
4. 单位换算与汇总
5. 多期结果与质量检查

## 1. 输入检查

输入必须是单波段整数分类栅格，编码与 `config/landuse_classes.md` 一致。统计前确认：

- 使用适合研究区的投影坐标系；
- 像元单位为米，或明确掌握实际像元面积；
- 研究区掩膜、NoData 和 0 类含义明确；
- 多期栅格已按 `projection_resample.md` 严格对齐；
- 后处理版本和原始分类版本没有混用。

不要在 EPSG:4326 中直接用“度 × 度”换算平方米，也不要用 EPSG:3857 进行正式面积统计。

## 2. 属性表法：单幅分类图总面积

路径：`Data Management Tools → Raster → Raster Properties → Build Raster Attribute Table`

该工具适用于离散整数栅格，不能为 32 位浮点栅格构建属性表。打开属性表后应包含 `VALUE` 和 `COUNT`。

若投影栅格像元宽、高分别为 `cellWidth`、`cellHeight`（米），则：

```text
Area_m2 = COUNT × abs(cellWidth × cellHeight)
Area_hm2 = Area_m2 / 10000
Area_km2 = Area_m2 / 1000000
Percent = Area_m2 / 有效分类总面积 × 100
```

在属性表中新增 Double 字段 `Area_m2`、`Area_hm2`、`Area_km2`、`Percent`，用 Calculate Field 计算。不要把 30 m 或 10 m 写死：投影、重采样后的实际像元尺寸可能已经改变。

仅在确认仍为原生正方形网格时，可快速核对：

| 分辨率 | 单像元面积 | hm² 换算 |
|---|---:|---:|
| 30 m | 900 m² | `COUNT × 0.09` |
| 10 m | 100 m² | `COUNT × 0.01` |
| 100 m | 10000 m² | `COUNT × 1` |

## 3. Tabulate Area 法：分区或批量统计

路径：`Spatial Analyst Tools → Zonal → Tabulate Area`

适用于按矿区、行政区、修复区或其他分区统计各地类面积：

- Input Zone Data：矿区/行政区要素或整数分区栅格；
- Zone Field：唯一且稳定的分区 ID；
- Input Class Data：土地利用分类栅格；
- Class Field：`VALUE`；
- Processing Cell Size：master grid 的像元大小；
- Environments：设置 Snap Raster、Extent、Cell Size、Mask 和 Output Coordinate System。

若分区要素作为输入，工具会内部栅格化；若两个栅格未对齐，工具会内部重采样。为保证可重复，应预先对齐并显式设置环境。输入栅格必须为整数类型。

输出列通常对应各类别面积。将字段重命名或另建整洁表，避免直接依赖自动生成的 `VALUE_1` 等字段含义。

## 4. 面积表结构

推荐输出 CSV/XLSX 字段：

| 字段 | 含义 |
|---|---|
| `zone_id` | 矿区或分区唯一编号 |
| `year` | 分类年份 |
| `class_code` | 类别编码 |
| `class_name` | 类别名称 |
| `pixel_count` | 像元数（若适用） |
| `area_m2` | 平方米 |
| `area_hm2` | 公顷/平方百米 |
| `area_km2` | 平方千米 |
| `percent` | 占有效分类面积百分比 |
| `lulc_version` | 分类图版本 |

NoData 和未分类 0 类应单独统计并说明是否计入分母。缺失类别应写为面积 0，不应删除整行导致后续年份表结构不一致。

## 5. 多期结果与质量检查

- 各类别面积之和应等于有效分类面积，并与研究区栅格化面积近似一致；
- 边界差异通常来自像元中心规则，需记录分辨率和掩膜方法；
- 检查异常类别值、负面积、重复分区和百分比是否合计约 100%；
- 多期比较必须使用相同网格、掩膜和编码；
- 总面积变化只能说明净变化，不能替代两期栅格叠加得到的土地利用转移矩阵；
- 不建议先 Raster to Polygon 再统计面积，除非确需矢量成果；转换会增加数据量并可能引入边界处理差异。

每次统计保存参数截图或地理处理历史，并记录 ArcGIS Pro 版本、输入文件哈希/版本、分析坐标系和 master grid。
