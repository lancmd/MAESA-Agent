# 从数据文件到本地工作流

智能体可以调用 `build_local_project_from_inputs`，直接用本地路径创建项目，再调用 `run_local_project`。不需要手写 `workflow_job.json`。

最小数据组合如下：

- 至少两期带年份的多波段遥感影像；
- 矿区边界；
- 碳密度 CSV；
- PLUS 驱动因子，其中 DEM 可自动派生坡度和坡向；
- `w.dat` 或已经生成的沉陷深度 GeoTIFF；
- 分类所需的二选一输入：已验证的 PyTorch 模型包，或 ENVI ROI 样本。

构建器会生成 `inputs.imagery_periods`。运行时依次产生每期 LULC、相邻期转移 CSV 和 Sankey SVG、统一网格的驱动因子、ND/UD/EP/RE 请求和输出验证、各情景 InVEST Carbon 结果及其成果清单。每个分类图、PLUS 情景图和 InVEST 栅格还会生成不依赖 `.aprx` 的 SVG 主题图（标题、图例、CRS 和显示分辨率）；如有现成的 ArcGIS Pro 布局，可继续启用 `gis_outputs` 输出出版级 PDF/PNG。

`w.dat` 的坐标被视为最新 LULC 网格的 CRS。构建项目时应填写原文件的单位和正负约定；流程会将其转换为 `m`、`positive_down`，再在主网格上按最近 PIM 样点补足像元。生成的 metadata 会保留这一插值说明，供后续核查。

水源供给、生境质量和综合生态服务还需要模型参数，而不是单靠遥感影像能够可靠推出。Annual Water Yield 至少需要降水、蒸散、土壤深度/PAWC、分区和生物物理表；Habitat Quality 需要威胁图层、敏感性和可达性参数。项目在没有这些本地 datastack 时会将该部分保持为 `pending_validation`，不会以虚构参数生成图。

PLUS V1.4.1 仍由本机 GUI 接收每个情景的请求包。系统会自动接管写入 `outputs/plus/<scenario>/PLUS_<scenario>.tif` 的结果，但不会把 GUI 的 `prepared` 状态误报为预测完成。
