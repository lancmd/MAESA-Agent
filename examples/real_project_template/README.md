# 真实项目模板

这个目录用于建立自己的六期分类—InVEST 项目，不含矿区数据。复制整个目录到工作位置，移除 `project.json.example` 的 `.example` 后缀，并把 `data/` 下的文件放到相应目录。

```powershell
Copy-Item -Recurse .\examples\real_project_template D:\MAESA\my_project
Rename-Item D:\MAESA\my_project\project.json.example project.json
cd D:\MAESA\my_project
python ..\MAESA-Agent\scripts\project_validator.py --project .\project.json
python ..\MAESA-Agent\scripts\project_workflow.py --project .\project.json --run
```

`project.json.example` 默认是 `classification_invest`：六期 ENVI 监督分类、逐期 ROI、逐期独立精度评价、Carbon 和 Habitat Quality。它不启动 PLUS；在需要 PLUS 时，复制 `templates/local_project.json` 中的 `plus` 配置并补充至少两期对齐 LULC 与驱动因子。

## 数据目录

| 目录 | 放入内容 |
|---|---|
| `data/imagery/` | 六期多波段 GeoTIFF。10 m Sentinel 会在分类后按多数值聚合到固定 30 m 主网格。 |
| `data/roi/` | 每期独立训练 ROI，含 `class_id` 字段、有效几何和 CRS。 |
| `data/validation/` | 每期独立 CSV，含 `reference`、`x`、`y`；坐标系写入项目的 `samples_crs`。 |
| `data/boundaries/` | 矿区边界；PLUS/沉陷分析可另放工作面边界。 |
| `data/drivers/` | DEM、道路/河流距离等驱动因子；其分类或连续类型在项目中声明。 |
| `data/invest/` | `carbon_density.csv`、Habitat Quality 配置、威胁栅格和其他 InVEST 数据栈文件。 |

先运行 `..\MAESA-Agent\scripts\maesa_doctor.ps1 -Project .\project.json`。若本机执行策略阻止脚本，使用 `powershell -ExecutionPolicy Bypass -File ..\MAESA-Agent\scripts\maesa_doctor.ps1 -Project .\project.json`。随后运行项目校验。校验只检查路径和配置；工作流中的 `classification_input_preflight` 会在 ENVI 打开前检查 ROI 字段、类别数、几何、CRS 与逐类验证样本数。

Carbon 参数报告写到 `runtime/validation/invest_carbon_<year>_parameter_report.md`；Habitat Quality 报告写到同一目录。两者都来自实际 datastack，而不是示例说明。
