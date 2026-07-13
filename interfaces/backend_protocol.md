# 矿区 GIS 本地后端协议 v1

MCP 服务运行在用户机器上，并把结构化任务交给本机软件进程。注册表接受三种连接方式：本地命令、回环 socket，以及仅限 `localhost`、`127.0.0.1` 或 `::1` 的 HTTP。公网地址、远程回调和令牌转发不属于本协议。

## 请求与响应

```json
{
  "protocol_version": "1.0",
  "request_id": "uuid",
  "operation": "arcgis.run_operations",
  "parameters": {}
}
```

```json
{
  "protocol_version": "1.0",
  "request_id": "uuid",
  "status": "completed",
  "outputs": [],
  "metrics": {},
  "error": null
}
```

可用状态为 `accepted`、`running`、`completed`、`prepared`、`pending_validation`、`waiting_interactive`、`failed` 和 `cancelled`。`prepared` 只表示本地任务包或脚本已经生成。

## 操作

| 操作 | 本地后端 | 用途 |
|---|---|---|
| `system.capabilities` | 全部 | 返回软件版本、桥接状态和限制 |
| `dataset.inspect` | ArcGIS | 检查 CRS、范围、分辨率、NoData 与数据类型 |
| `arcgis.run_operations` | ArcGIS | 运行栅格处理、复合碳储与自动制图操作 |
| `envi.supervised_classification` | ENVI | 运行最大似然或最小距离分类 |
| `pytorch.validate_model` / `pytorch.run_lulc_inference` | PyTorch | 校验模型包与分块推理 |
| `plus.run_scenario` | PLUS 本地桥接器 | 运行 ND、UD、EP、RE；无桥接器时生成任务包 |
| `invest.run_carbon` / `invest.run_model` | InVEST | 运行 Carbon、水源供给或生境质量 |
| `project.validate` / `project.compile_workflow` / `project.run_workflow` | 项目后端 | 校验、编译并运行本地项目 |
| `analysis.validate_results` | 项目后端 | 汇总分析与地图验收证据 |
| `analysis.lulc_accuracy` / `analysis.plus_validation` | 项目后端 | 计算分类精度、FoM 和多种子稳定性 |
| `analysis.invest_consistency` | 项目后端 | 对比流程与独立 InVEST Carbon 栅格 |
| `ecosystem.sensitivity_analysis` | 生态服务后端 | 检查权重扰动后的得分与排序变化 |

RE 请求中的 `resource_extraction` 使用统一字段：`core_driver_input`、`core_driver_unit: "m"`、`core_driver_convention: "positive_down"` 与 `additional_driver_factors`。项目配置里的 `inputs.subsidence_depth_raster` 会在编译时解析为 `core_driver_input` 的本机 TIFF 路径。原始 `w.dat`、彩色云图和等值线图不作为 PLUS 数值输入。

本地桥接器应返回绝对产物路径、运行日志、软件版本、输入摘要与关键空间元数据。源数据保持只读，派生文件写入项目工作目录。
