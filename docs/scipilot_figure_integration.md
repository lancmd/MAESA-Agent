# SciPilot 论文分析图工作流

仓库的论文分析图现在可以使用本机安装的 `scipilot-figure-skill` 生成。安装位置由 Codex Skill Installer 管理，不把第三方技能源码复制进本仓库。

## 已接入的步骤

1. 用 `profile_data.py` 对四情景土地需求、历史服务统计和 2026 服务统计做数据剖析；
2. 用 `setup_style.py` 配置中文字体和出版级 Matplotlib 样式；
3. 时间序列用折线图，情景×地类需求用热力图，四情景服务比较用点图；
4. 用 `export_figure.py` 输出 PDF、SVG、600 dpi PNG 及灰度预览；
5. 用 `check_figure.py` 做 DPI、格式和字体嵌入检查，并保留视觉复核预览。

## 重绘命令

```powershell
.\.venv\Scripts\python.exe scripts\render_scipilot_analysis.py `
  --root C:\path\to\project
```

结果位于：

`<project-root>\outputs\论文分析结果\scipilot_figures`

主图 PNG 通过 `check_figure.py --strict --min-dpi 300`；灰度预览是辅助检查图，不作为投稿主图。
