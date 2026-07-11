# 匿名小型示例

`huaibei_demo` 只是项目目录名；这里没有真实矿区、遥感观测、坐标位置或研究结论。`synthetic_data.py` 每次用固定随机种子生成 64 × 64 像元、30 m 分辨率的匿名数据，用于检查本地工作流能否读取栅格、边界、碳密度、PLUS RE 驱动因子和生态服务指标。

示例默认直接使用生成的 `lulc_2025.tif`，因此不要求训练样本或深度学习模型即可验证项目配置和工作流编译。它将编译 ND、UD、EP、RE 四个 PLUS 阶段、一个 InVEST Carbon 阶段和一个 AHP 生态服务阶段。实际执行 PLUS 仍取决于本机 PLUS 适配器是否可用；本示例不会伪装该软件已经运行。

## 最小依赖

生成输入数据只需 Python 3.10+、`numpy` 和 `rasterio`。在已完成项目安装的虚拟环境中执行：

```powershell
& .\.venv\Scripts\python.exe -m pip install numpy rasterio
& .\.venv\Scripts\python.exe .\examples\huaibei_demo\synthetic_data.py
```

若希望同时生成一个最小 PyTorch 导出模型包，额外安装 `torch` 并附加 `--with-model`：

```powershell
& .\.venv\Scripts\python.exe .\examples\huaibei_demo\synthetic_data.py --with-model
```

该模型只验证模型包和分块推理接口；它不是可用于土地利用研究的训练模型。

## 可重复检查

从仓库根目录依次运行：

```powershell
& .\.venv\Scripts\python.exe .\examples\huaibei_demo\synthetic_data.py
& .\.venv\Scripts\python.exe .\scripts\project_validator.py --project .\examples\huaibei_demo\project.json
& .\.venv\Scripts\python.exe .\scripts\project_workflow.py --project .\examples\huaibei_demo\project.json
& .\.venv\Scripts\python.exe .\scripts\analysis_validation.py --validation-file .\examples\huaibei_demo\expected_outputs.json --output-report .\examples\huaibei_demo\runtime\analysis_validation_report.json
```

第二步应返回 `valid`。第三步应生成 `runtime/generated/workflow_job.json`，其中阶段顺序为 `plus_ND`、`plus_UD`、`plus_EP`、`plus_RE`、`invest_carbon`、`ecosystem_service`。第四步检查分类、PLUS、InVEST、生态服务与地图的验收报告格式；其 `completed` 仅说明合成基准值符合验收契约，并不代表真实分析已经通过。

`benchmark.csv` 列出这些合成验收值和容差。`screenshots/` 保留为空，用于本地运行后保存已审核地图的截图；生成的数据和运行结果均由 `.gitignore` 排除，避免把临时产物提交到仓库。

本机 InVEST 和其他启用的软件已经配置好时，可以把编译与执行合并为一条命令：

```powershell
& .\.venv\Scripts\python.exe .\scripts\project_workflow.py --project .\examples\huaibei_demo\project.json --run --continue-on-error
```

没有 PLUS 本地桥接器时，四个 PLUS 阶段会保留为 `prepared`；本机可运行的 InVEST 和生态服务阶段仍可继续完成。
