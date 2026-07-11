# 沉陷积水复合碳库核算

标准 InVEST Carbon 按土地利用类别的平均面积碳密度计算。沉陷积水的水深、库容、水生植被和底泥差异较大时，可将该地类改用复合碳库核算：水体碳、水生植被碳和底泥碳分别计算，再替换标准 InVEST 中的沉陷积水面积碳。

## 1. 适用数据

复合核算至少需要以下数据：

- 与下沉地形同一时期、同一坐标基准的遥感沉陷积水边界；
- 水体库容，或可计算库容的水深/水下地形；
- 水体碳密度（g C/m³）；
- 水生植被覆盖面积和碳密度（Mg C/ha）；
- 底泥覆盖面积和碳密度（Mg C/ha）；
- 每个参数的来源、时间和不确定性说明。

若只有平面水体面积而没有库容或代表性水深，可使用标准 InVEST 面积法，并在结果中说明其局限。

## 2. 组分公式

### 水体碳

```text
C_water_Mg = V_water_m3 × D_water_g_m3 / 1,000,000
```

### 水生植被碳

```text
C_veg_Mg = A_veg_ha × D_veg_Mg_ha
```

### 底泥碳

```text
C_sed_Mg = A_sed_ha × D_sed_Mg_ha
```

### 复合碳库

```text
C_composite_Mg = C_water_Mg + C_veg_Mg + C_sed_Mg
```

模板：`templates/subsidence_water_components_template.csv`。

水样与水生植被归入地上组分，底泥归入土壤组分，地下组分单独记录。水体碳密度是体积密度，因此保留“库容 × 体积密度”的量纲，不能直接写入面积碳密度字段。

## 3. 库容

将遥感提取的积水边界与外部概率积分法产生的下沉地形在同一空间基准下匹配，再以水面高程和逐单元水深计算库容。计算采用正水深：

```text
bed_elevation_m = pre_mining_dem_m - positive_subsidence_depth_m
depth_m = max(water_surface_elevation_m - bed_elevation_m, 0)
volume_m3 = Σ(depth_m × pixel_area_m2)
```

所有高程使用同一垂直基准和单位。PIM 下沉等值线可用于检查库容反演，但不能把下沉量直接视为水深。

若输入为外部 PIM 软件的 `w.dat`，先用 `scripts/wdat_to_depth.py` 标准化为正的 `subsidence_depth_m`，再在 ArcGIS Pro 中栅格化并与主网格对齐：

```text
post_mining_elevation = pre_mining_dem - subsidence_depth_m
water_depth = max(water_level_elevation - post_mining_elevation, 0)
water_volume = Σ(water_depth × pixel_area)
```

因此，`w.dat` 可以参与库容判断，但还需要基准 DEM、水面高程、共同的坐标与垂直基准以及遥感积水边界。工作面范围只作为裁剪或约束，不能单独推得库容。`scripts/arcgis_ops.py` 的 `subsidence_water_carbon` 会输出水深栅格、库容表和三组分碳表。

## 4. 水生植被面积

水生植被面积优先采用实测或遥感解译边界。没有边界时，可在项目中提供经过本地调查确认的水深阈值，得到潜在面积：

```text
A_veg = A_water - A(depth > local_threshold_m)
```

阈值受物种、季节和场地条件影响。采用阈值法时，结果标记为 `potential`，并记录阈值来源；采用遥感分类时，记录传感器、季节、类别精度以及是否包括漂浮、挺水或沉水植被。植被面积不应超过水体面积。

## 5. 底泥面积

底泥面积来自测量、沉积范围解释或明确假设，不自动等同于水体面积。若以全水底作为底泥覆盖范围，在任务中设置 `bottom_sediment_assume_full_waterbed=true`，让输出表记录这一假设。

底泥碳密度应说明取样深度、容重、有机碳含量和干湿重换算方式。

## 6. 与 InVEST 合并：替换而非叠加

先计算 InVEST 中沉陷积水的基准碳量：

```text
C_invest_subsidence_water_Mg
= A_subsidence_water_ha
× (c_above + c_below + c_soil + c_dead)
```

再计算增强总碳：

```text
C_total_enhanced_Mg
= C_invest_total_Mg
- C_invest_subsidence_water_Mg
+ C_composite_Mg
```

如需同时展示标准面积法和增强法，应并列呈现两者，不能相加。

## 7. 不确定性

建议至少对以下变量设置低、中、高情景：

- 水体边界与库容；
- 水体碳浓度的季节变化；
- 水生植被覆盖面积与碳密度；
- 底泥覆盖范围、深度和碳密度。

报告各组分对总量的贡献和敏感性。底泥占比较高时，应重点复核面积、采样厚度和单位换算。
