# 软件适配器

## 接入原则

智能体只调用 `interfaces/backend_protocol.md` 中的标准操作，不直接绑定软件安装目录。优先使用 MCP 连接已注册的 HTTP、socket、桌面插件或云端后端；`scripts/workflow_agent.py`、ArcPy 和本地 InVEST CLI 只是协议的一种实现。每个桥接器必须通过 `system.capabilities` 报告真实版本、可用操作、许可/认证状态与限制。

## ArcGIS Pro

ArcGIS 桥接器可运行于 Pro 插件、地理处理服务或本地 ArcPy 环境。仓库自带的本地实现通过 `propy.bat` 运行 `scripts/arcgis_ops.py`，支持投影、重采样、掩膜裁剪、坡度坡向、距离栅格、属性表、面积统计和转移组合。分类栅格使用 `NEAREST`，连续栅格默认使用 `BILINEAR`。所有操作设置 `snapRaster`、`cellSize`、`extent` 与 `mask` 时应指向同一主网格。

## InVEST

InVEST 可由远程服务、容器或本地命令桥接器运行 datastack。本地实现使用模型标识 `carbon`，把模型工作目录和任务总工作目录分开。完成后必须检查 InVEST 日志及版本对应产物，并用像元面积乘碳密度进行数量级闭合检查。

## ENVI

ENVI 桥接器在有许可的 ENVI 进程或服务器中实现 `envi.supervised_classification`。仓库的 IDL 模板可作为桥接器内部实现，但 MCP 客户端不需要知道 IDL 路径。最大似然与最小距离应使用同一套训练/验证样本再比较精度。许可初始化失败时阶段状态为 `failed` 或 `waiting_interactive`，不得伪造输出。

## Google Earth Engine

GEE 后端可使用 Earth Engine Python/REST API、服务账号、已认证用户会话或任务队列实现 `gee.export_imagery`。后端负责返回任务 ID并跟踪导出；本地渲染 `gee_codes/*.js` 只是无认证时的兜底。脚本生成不是影像导出完成。

## PLUS

PLUS 不同发布版本的自动化入口不统一，因此由对应版本的桥接器实现 `plus.run_scenario` 并在能力响应中声明参数模式。桥接器可包装 GUI 插件、宏、进程控制或服务化版本；智能体不得猜测命令行参数。没有桥接器时只能完成输入对齐与任务包，状态标记为 `prepared`。

## 开放 GIS 后端

GDAL、QGIS、GeoPandas、rioxarray 等可用于等价批处理。替换前必须确认分类值不被插值、目标 CRS 合理、像元网格与主栅格严格对齐，并保留命令与版本信息。
