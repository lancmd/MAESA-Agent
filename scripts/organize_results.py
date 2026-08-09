#!/usr/bin/env python3
"""Package verified figures and tables into the user-facing 结果 directory.

Only the canonical historical map exports and analysis artifacts are copied.
The old PLUS 2026 figures are intentionally excluded because their four
scenarios were not independently validated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

YEARS = (2005, 2010, 2015, 2020, 2025)
FOLDERS = (
    "\u571f\u5730\u5229\u7528\u5206\u7c7b", "\u78b3\u50a8\u91cf", "\u6c34\u6e90\u4f9b\u7ed9", "\u751f\u5883\u8d28\u91cf",
    "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1", "\u5206\u6790\u7edf\u8ba1\u56fe\u4e0e\u8868", "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635", "\u6851\u57fa", "\u65f6\u7a7a\u5206\u5e03",
)
EXTS = {".png", ".pdf", ".svg", ".csv", ".json", ".md", ".txt"}


def copy_file(src: Path, dst: Path, copied: list[Path]) -> None:
    if not src.is_file() or src.suffix.lower() not in EXTS:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(dst)


def copy_tree_files(src_root: Path, dst_root: Path, copied: list[Path]) -> None:
    if not src_root.is_dir():
        return
    for src in sorted(src_root.rglob("*")):
        if src.is_file():
            copy_file(src, dst_root / src.relative_to(src_root), copied)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    result = root / "结果"
    result.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS:
        (result / folder).mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    # Canonical ArcGIS/Matplotlib annual maps.  The source has no unverified
    # scenario maps in this historical subtree.
    annual = root / "maps" / "论文出图_20260806" / "历史时期"
    routes = {
        "\u571f\u5730\u5229\u7528\u5206\u7c7b": "\u571f\u5730\u5229\u7528\u5206\u7c7b",
        "\u78b3\u50a8\u91cf": "\u78b3\u50a8\u91cf",
        "\u6c34\u6e90\u4f9b\u7ed9": "\u6c34\u6e90\u4f9b\u7ed9",
        "\u751f\u5883\u8d28\u91cf": "\u751f\u5883\u8d28\u91cf",
        "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1": "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1",
    }
    for year in YEARS:
        for src in sorted((annual / str(year)).glob("*")):
            for key, folder in routes.items():
                if key in src.name:
                    copy_file(src, result / folder / "\u5386\u53f2\u65f6\u671f" / str(year) / src.name, copied)
                    break

    # Latest analysis products: keep reproducible tables/figures, not large
    # intermediate rasters.  Preserve their small subfolders for provenance.
    analysis = root / "outputs" / "\u8bba\u6587\u5206\u6790\u7ed3\u679c_20260807"
    copy_tree_files(analysis, result / "\u5206\u6790\u7edf\u8ba1\u56fe\u4e0e\u8868", copied)

    # Older run contains the completed transition, Sankey and spatiotemporal
    # figure families; copy only those named products.
    old = root / "outputs" / "\u8bba\u6587\u5206\u6790\u7ed3\u679c_20260806"
    copy_tree_files(old / "\u65f6\u7a7a\u5206\u5e03\u56fe", result / "\u65f6\u7a7a\u5206\u5e03", copied)
    for src in old.glob("*"):
        if not src.is_file():
            continue
        if "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635" in src.name:
            copy_file(src, result / "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635" / src.name, copied)
        if "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u6851\u57fa" in src.name:
            copy_file(src, result / "\u6851\u57fa" / src.name, copied)
    sankey_source = root / "outputs" / "figures"
    for src in sankey_source.glob("*sankey*"):
        copy_file(src, result / "\u6851\u57fa" / src.name, copied)

    readme = result / "README.md"
    readme.write_text(
        "# 皖北六市矿区生态服务结果\n\n"
        "本目录按成果类型整理了五个历史年份（2005、2010、2015、2020、2025）的地图、统计表、转移矩阵、桑基图和时空分布图。\n\n"
        "`分析统计图与表/矿区专题分析` 中为潘集第三煤矿、临涣煤矿、钱营孜煤矿、谢桥煤矿和许疃煤矿的专题面板。早期年份没有独立沉陷积水证据时，面板按标准六类体系显示；2025 年使用现有增强七类栅格。\n\n"
        "旧版 PLUS 四情景图未纳入本目录：当前运行尚处于 GUI 交接/输出等待状态，旧文件不具备独立验证记录。待 ND、UD、EP、RE 均检测到真实栅格并完成 FoM、关键地类精度和多种子稳定性验证后，再按情景追加。\n\n"
        "文件来源和 SHA-256 记录见 `manifest.json`。输入数据、计算栅格和 PLUS 运行目录仍保留在项目原目录，便于复算。\n",
        encoding="utf-8",
    )
    # Include pre-existing generated subtrees (for example mine专题分析)
    # rather than limiting provenance to files copied in this invocation.
    manifest = []
    for path in sorted(p for p in result.rglob("*") if p.is_file() and p.name != "manifest.json"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append({"path": str(path.relative_to(result)), "bytes": path.stat().st_size, "sha256": digest})
    (result / "manifest.json").write_text(json.dumps({"years": YEARS, "files": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "result": str(result), "folders": list(FOLDERS), "copied_files": len(copied)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
