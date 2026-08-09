# 论文成果汇总与单位契约

`scripts/build_wanbei_report_assets.py` 从项目工作区的正式栅格、统计 CSV 和情景输出中重新汇总图表数据；`scripts/build_ecosystem_service_report.py` 将这些数据、三线表和已经验收的图片组织为 DOCX。两者均面向本地工作区，不把原始影像、矿区边界、碳密度或研究结论提交到仓库。

## 运行前提

- 完成空间预检，全部统计栅格与 LULC 使用同一投影网格和掩膜；
- Carbon、Annual Water Yield、Habitat Quality 与综合服务输出均已写入项目工作区；
- 以独立验证样本、PLUS 回代或现场资料核对的指标，仍应按实际状态写入 `pending_validation`，不能因文档生成成功而改为已验证；
- 报告脚本依赖 `rasterio`、`matplotlib` 和 `python-docx`。`setup_agent.ps1` 已通过 `reporting` 可选依赖安装它们。

## 统一单位

| 结果 | 栅格语义 | 汇总规则 | 制图单位 |
|---|---|---|---|
| InVEST Carbon `tot_c_cur.tif` | `Mg C/像元` | 有效像元直接求和 | 若表现密度，除以像元面积，单位 `Mg C/hm²` |
| Annual Water Yield | `mm` | `深度(mm) × 像元面积(m²) / 1000` | `mm` |
| 生境质量 | 0—1 指数 | 有效像元均值 | 指数值 |
| 综合生态服务 | 标准化指数 | 有效像元均值 | 指数值 |

不要对 `tot_c_cur` 的总和再次乘像元面积。30 m 方格的面积是 `0.09 hm²`，但报告脚本从 GeoTIFF 变换参数读取实际像元面积，以避免把假定网格写死。

## 本地执行

```powershell
.\.venv\Scripts\python.exe .\scripts\build_wanbei_report_assets.py --root C:\path\to\project
.\.venv\Scripts\python.exe .\scripts\build_ecosystem_service_report.py --root C:\path\to\project
```

DOCX 生成后应转换为 PDF 或 PNG 页面进行视觉检查，重点检查三线表不截字、地图图例不遮挡、连续色带带有单位，以及图题和正文中的统计数字与 CSV 一致。
