# 最终成果归档与清理

MAESA 将原始输入、运行工作区和最终成果分开管理。原始影像、ROI、验证样本、边界、驱动因子、沉陷数据和 InVEST 参数表不得因整理结果而移动或删除。

## 推荐结构

最终成果目录建议包含土地利用分类、碳储量、水源供给、生境质量、综合生态系统服务、分析图表、转移矩阵与桑基图、PLUS 四情景、InVEST 原生产出、报告以及统计和运行清单。中间栅格、GUI 截图、失败候选、旧报告和旧日期运行目录不应混入最终包。

## 受控归档

复制并编辑 [`templates/final_results_plan.example.json`](../templates/final_results_plan.example.json)。计划中的路径必须相对于项目根目录；`preserve` 应列出所有原始数据目录；`cleanup` 只能列出明确的派生目录。

先预览，不改动文件：

```powershell
python .\scripts\finalize_project_results.py `
  --project-root C:\path\to\project `
  --plan C:\path\to\final_results_plan.json
```

核对预览后执行：

```powershell
python .\scripts\finalize_project_results.py `
  --project-root C:\path\to\project `
  --plan C:\path\to\final_results_plan.json `
  --apply
```

脚本拒绝绝对路径、越界路径、项目根目录删除、最终目录自删除，以及与 `preserve` 重叠的清理目标。完成后写出 `final_results_manifest.json`；只有发布或长期归档确实需要时才增加 `--sha256`，以免大型栅格重复读取。

MCP 宿主可先调用 `finalize_project_results(..., apply=false)` 展示同一预览，在用户确认计划后再以 `apply=true` 执行。

归档不改变科研验证状态。`workflow_state.json`、`outputs_manifest.json`、`provenance.json`、`validation_summary.json` 以及 PLUS 各情景的栅格校验记录应随最终成果保留。
