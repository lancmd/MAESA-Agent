#!/usr/bin/env python3
"""Write the paper-oriented table inventory and AHP consistency table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    out = root / "outputs" / "论文分析结果_20260806"
    manifest = json.loads((out / "ecosystem_service_manifest.json").read_text(encoding="utf-8"))
    criteria = manifest["ahp"]["criteria_order"]
    matrix = np.asarray(manifest["ahp"]["pairwise_matrix"], dtype=float)
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    index = int(np.argmax(eigenvalues.real))
    lambda_max = float(eigenvalues[index].real)
    vector = np.abs(eigenvectors[:, index].real)
    weights = vector / vector.sum()
    n = matrix.shape[0]
    ci = (lambda_max - n) / (n - 1) if n > 1 else 0.0
    # Random index values used by the standard Saaty consistency test.
    ri = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32}.get(n, 1.41)
    cr = ci / ri if ri else 0.0
    write_csv(out / "AHP权重与一致性检验.csv", [
        {"指标": label, "权重": f"{weight:.6f}", "最大特征根": f"{lambda_max:.6f}",
         "CI": f"{ci:.6f}", "RI": f"{ri:.2f}", "CR": f"{cr:.6f}",
         "一致性结论": "通过" if cr < float(manifest["ahp"].get("consistency_threshold", 0.1)) else "不通过"}
        for label, weight in zip(criteria, weights)
    ])
    catalog = [
        ("土地利用面积统计.csv", "五期土地利用面积", "hm²"),
        ("土地利用转移矩阵_2005_2025.csv", "2005—2025土地利用转移矩阵", "像元数"),
        ("2026四情景土地利用需求_hm2.csv", "2026四情景土地需求（初始校准）", "hm²"),
        ("历史时期生态服务统计.csv", "五期碳储量、水源供给、生境质量和综合服务", "t C、m³、0—1"),
        ("2026年四情景生态服务统计.csv", "2026四情景服务汇总", "t C、m³、0—1"),
        ("各地类碳储量变化.csv", "各地类碳储量变化", "t C"),
        ("生境质量等级面积.csv", "生境质量等级面积", "hm²"),
        ("生态服务相关性矩阵.csv", "生态服务相关性矩阵", "Pearson r"),
        ("AHP权重与一致性检验.csv", "AHP权重和一致性检验", "权重、CI、CR"),
        ("增强分类编码映射.csv", "普通六类到高潜水位七类映射", "编码"),
    ]
    lines = ["# 论文结果表格清单", "", "所有面积统一为 30 m 主网格（0.09 hm²/像元）；碳储量单位为 t C，水源供给为 m³。", ""]
    for name, desc, unit in catalog:
        status = "已生成" if (out / name).is_file() else "待补齐"
        lines.append(f"- `{name}`：{desc}；单位：{unit}；状态：{status}。")
    lines.extend(["", f"AHP 最大特征根 λmax={lambda_max:.6f}，CI={ci:.6f}，CR={cr:.6f}；阈值 0.1，结论：{'通过' if cr < 0.1 else '不通过'}。", "", "2026 四情景土地需求采用本地 2020—2025 趋势与论文相对约束生成初始值，需通过 PLUS 本地转移矩阵和 FoM/各地类精度验证后再作为最终预测。"])
    (out / "论文结果表格清单.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "lambda_max": lambda_max, "CI": ci, "CR": cr}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
