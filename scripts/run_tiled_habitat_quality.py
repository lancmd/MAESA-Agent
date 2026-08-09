#!/usr/bin/env python3
"""Run InVEST Habitat Quality on overlapping 30 m tiles and mosaic core cells.

InVEST 3.12 can raise ``queue.Empty`` during a large, sparse full-extent
convolution on Windows.  Habitat degradation is local to each threat's maximum
distance, so an overlapping tiling scheme is equivalent for core cells when the
padding is at least the largest threat distance.  This runner keeps the source
analysis grid and invokes the installed InVEST executable for every tile; it
does not substitute a custom Habitat Quality formula.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Tile:
    row: int
    column: int
    core: tuple[int, int, int, int]
    padded: tuple[int, int, int, int]

    @property
    def key(self) -> str:
        return f"r{self.row:02d}_c{self.column:02d}"


def partition(width: int, height: int, columns: int, rows: int, padding_cells: int) -> list[Tile]:
    if columns < 1 or rows < 1:
        raise ValueError("tiles-x and tiles-y must be positive")
    if padding_cells < 0:
        raise ValueError("buffer-m must not be negative")
    result: list[Tile] = []
    for row in range(rows):
        y0, y1 = row * height // rows, (row + 1) * height // rows
        for column in range(columns):
            x0, x1 = column * width // columns, (column + 1) * width // columns
            padded = (max(0, x0 - padding_cells), max(0, y0 - padding_cells),
                      min(width, x1 + padding_cells), min(height, y1 + padding_cells))
            result.append(Tile(row, column, (x0, y0, x1, y1), padded))
    return result


def write_window(source_path: Path, output: Path, bounds: tuple[int, int, int, int]) -> None:
    import rasterio
    from rasterio.windows import Window

    x0, y0, x1, y1 = bounds
    window = Window(x0, y0, x1 - x0, y1 - y0)
    with rasterio.open(source_path) as source:
        profile = source.profile.copy()
        profile.update(width=int(window.width), height=int(window.height), transform=source.window_transform(window), compress="lzw")
        output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", **profile) as destination:
            for index in range(1, source.count + 1):
                destination.write(source.read(index, window=window), index)


def read_threats(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "threat" not in reader.fieldnames or "cur_path" not in reader.fieldnames:
            raise ValueError(f"Habitat Quality threat table has no threat/cur_path fields: {path}")
        rows = [dict(item) for item in reader]
        return rows, list(reader.fieldnames)


def write_threats(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def quality_output(workspace: Path, suffix: str) -> Path:
    candidates = sorted(workspace.rglob(f"quality_{suffix}.tif"))
    if not candidates:
        # InVEST 3.18 names current-landscape quality output quality_c_*.
        candidates = sorted(workspace.rglob(f"quality_c_{suffix}.tif"))
    if not candidates:
        candidates = sorted(workspace.rglob("quality*.tif"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one InVEST quality raster in {workspace}, found {len(candidates)}")
    return candidates[0]


def crop_quality_to_core(quality: Path, full_output: Path, tile: Tile, source_grid: Path) -> int:
    """Copy the unpadded core by georeferenced window, rejecting edge truncation."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window, bounds as window_bounds, from_bounds

    x0, y0, x1, y1 = tile.core
    core = Window(x0, y0, x1 - x0, y1 - y0)
    with rasterio.open(source_grid) as reference, rasterio.open(quality) as source, rasterio.open(full_output, "r+") as destination:
        left, bottom, right, top = window_bounds(core, reference.transform)
        requested = from_bounds(left, bottom, right, top, source.transform).round_offsets().round_lengths()
        if requested.col_off < 0 or requested.row_off < 0 or requested.col_off + requested.width > source.width or requested.row_off + requested.height > source.height:
            raise RuntimeError(f"{tile.key}: InVEST output does not cover the full unpadded core")
        if int(requested.width) != int(core.width) or int(requested.height) != int(core.height):
            raise RuntimeError(f"{tile.key}: InVEST output cell grid differs from source tile grid")
        values = source.read(1, window=requested)
        nodata = source.nodata
        invalid = ~np.isfinite(values)
        if nodata is not None:
            invalid |= values == nodata
        result = values.astype("float32", copy=False)
        result[invalid] = -1.0
        destination.write(result, 1, window=core)
        return int((~invalid).sum())


def write_sensitivity(source: Path, destination: Path, *, modern_cli: bool) -> None:
    """Copy the sensitivity table, translating the 3.12 LULC header for 3.18."""
    if not modern_cli:
        shutil.copy2(source, destination)
        return
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Habitat Quality sensitivity table has no header: {source}")
        fields = list(reader.fieldnames)
        if "lucode" not in fields:
            if "lulc" not in fields:
                raise ValueError("Habitat Quality sensitivity table needs lucode (or legacy lulc) column")
            fields[fields.index("lulc")] = "lucode"
        rows = []
        for row in reader:
            item = dict(row)
            if "lucode" not in item and "lulc" in item:
                item["lucode"] = item.pop("lulc")
            rows.append(item)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_tile_stack(base_stack: dict[str, Any], tile_dir: Path, tile: Tile, source_grid: Path,
                     *, modern_cli: bool) -> Path:
    arguments = dict(base_stack.get("args", {}))
    if not isinstance(arguments.get("lulc_cur_path"), str):
        raise ValueError("Habitat Quality datastack needs args.lulc_cur_path")
    threats_path = Path(str(arguments.get("threats_table_path", ""))).expanduser().resolve()
    sensitivity_path = Path(str(arguments.get("sensitivity_table_path", ""))).expanduser().resolve()
    if not threats_path.is_file() or not sensitivity_path.is_file():
        raise ValueError("Habitat Quality datastack threat/sensitivity table does not exist")
    inputs = tile_dir / "inputs"
    write_window(Path(arguments["lulc_cur_path"]).expanduser().resolve(), inputs / "lulc.tif", tile.padded)
    rows, fields = read_threats(threats_path)
    for row in rows:
        source = Path(str(row.get("cur_path", ""))).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"threat raster is missing: {source}")
        name = str(row["threat"]).strip() or "threat"
        target = inputs / f"threat_{name}.tif"
        write_window(source, target, tile.padded)
        row["cur_path"] = str(target)
        if "fut_path" in row:
            row["fut_path"] = ""
    local_threats = inputs / "threats.csv"
    write_threats(local_threats, rows, fields)
    local_sensitivity = inputs / "sensitivity.csv"
    write_sensitivity(sensitivity_path, local_sensitivity, modern_cli=modern_cli)
    suffix = f"hq_{tile.key}"
    arguments.update({"lulc_cur_path": str(inputs / "lulc.tif"), "threats_table_path": str(local_threats),
                      "sensitivity_table_path": str(local_sensitivity), "n_workers": -1 if modern_cli else 1,
                      "results_suffix": suffix})
    if modern_cli:
        arguments["workspace_dir"] = str(tile_dir / "invest_workspace")
    stack = {"model_name": "natcap.invest.habitat_quality", "args": arguments,
             "invest_version": base_stack.get("invest_version"), "tiling": {"tile": tile.key, "padded_window": tile.padded, "core_window": tile.core}}
    stack_path = tile_dir / "datastack.json"
    write_json(stack_path, stack)
    return stack_path


def run(args: argparse.Namespace) -> dict[str, Any]:
    import rasterio

    stack_path = args.datastack.expanduser().resolve()
    executable = args.invest_exe.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not stack_path.is_file() or not executable.is_file():
        raise ValueError("datastack and invest executable must be existing local files")
    stack = load_json(stack_path)
    source_grid = Path(str(stack.get("args", {}).get("lulc_cur_path", ""))).expanduser().resolve()
    if not source_grid.is_file():
        raise ValueError("datastack args.lulc_cur_path is missing")
    with rasterio.open(source_grid) as source:
        if not source.crs or not source.crs.is_projected or source.transform.a <= 0:
            raise ValueError("Habitat Quality source grid must be projected")
        cell_size = abs(float(source.transform.a))
        padding_cells = int(round(float(args.buffer_m) / cell_size))
        tiles = partition(source.width, source.height, args.tiles_x, args.tiles_y, padding_cells)
        profile = source.profile.copy()
        profile.update(count=1, dtype="float32", nodata=-1.0, compress="lzw")
    if float(args.buffer_m) + cell_size * 1e-6 < float(args.required_buffer_m):
        raise ValueError("buffer-m must be at least required-buffer-m for the declared threat distances")
    workspace = args.workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = workspace / "tiled_habitat_quality_report.json"
    reports: list[dict[str, Any]] = []
    completed: dict[str, dict[str, Any]] = {}
    if args.resume:
        if not output.is_file() or not report_path.is_file():
            raise ValueError("--resume needs both the existing mosaic and tiled_habitat_quality_report.json")
        previous = load_json(report_path)
        old_tiles = previous.get("tiles", [])
        if not isinstance(old_tiles, list):
            raise ValueError("existing tiled_habitat_quality_report.json has no valid tiles list")
        for item in old_tiles:
            if isinstance(item, dict) and item.get("status") == "completed" and isinstance(item.get("tile"), str):
                completed[str(item["tile"])] = item
        reports = [completed[key] for key in sorted(completed)]
    else:
        if output.exists():
            raise FileExistsError(f"refusing to overwrite an existing Habitat Quality mosaic: {output}; use --resume or a new output path")
        with rasterio.open(output, "w", **profile) as mosaic:
            import numpy as np
            for _, window in mosaic.block_windows(1):
                mosaic.write(np.full((int(window.height), int(window.width)), -1.0, dtype="float32"), 1, window=window)
    write_json(report_path, {"status": "running", "tiles": reports, "output": str(output),
                             "grid": str(source_grid), "buffer_m": args.buffer_m,
                             "tile_count": len(tiles), "resume": bool(args.resume)})
    for tile in tiles:
        if tile.key in completed:
            continue
        tile_dir = workspace / "tiles" / tile.key
        tile_workspace = tile_dir / "invest_workspace"
        modern_cli = args.invest_cli_profile == "modern_3_18"
        local_stack = build_tile_stack(stack, tile_dir, tile, source_grid, modern_cli=modern_cli)
        if modern_cli:
            command = [str(executable), "-vv", "run", "habitat_quality", "-d", str(local_stack), "-w", str(tile_workspace)]
        else:
            command = [str(executable), "run", "habitat_quality", "--headless", f"--datastack={local_stack}", f"--workspace={tile_workspace}"]
        log = tile_dir / "invest_stdout.log"
        try:
            process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=args.timeout_seconds, check=False)
        except subprocess.TimeoutExpired as error:
            text = error.stdout if isinstance(error.stdout, str) else ""
            log.write_text(text + f"\n[MAESA] timed out after {args.timeout_seconds} seconds.\n", encoding="utf-8")
            tile_report = {"tile": tile.key, "core_window": tile.core, "padded_window": tile.padded,
                           "datastack": str(local_stack), "workspace": str(tile_workspace), "log": str(log),
                           "status": "timed_out", "timeout_seconds": args.timeout_seconds}
            reports.append(tile_report)
            write_json(report_path, {"status": "timed_out", "tiles": reports, "output": str(output),
                                     "grid": str(source_grid), "buffer_m": args.buffer_m, "tile_count": len(tiles)})
            raise RuntimeError(f"InVEST Habitat Quality timed out for {tile.key}; rerun with --resume after reducing tile size or increasing timeout") from error
        log.write_text(process.stdout or "", encoding="utf-8")
        tile_report: dict[str, Any] = {"tile": tile.key, "core_window": tile.core, "padded_window": tile.padded,
                                       "datastack": str(local_stack), "workspace": str(tile_workspace), "log": str(log), "returncode": process.returncode}
        if process.returncode != 0:
            tile_report["status"] = "failed"
            reports.append(tile_report)
            write_json(report_path, {"status": "failed", "tiles": reports, "output": str(output)})
            raise RuntimeError(f"InVEST Habitat Quality failed for {tile.key}; see {log}")
        quality = quality_output(tile_workspace, f"hq_{tile.key}")
        tile_report.update({"status": "completed", "quality": str(quality), "valid_core_pixels": crop_quality_to_core(quality, output, tile, source_grid)})
        reports.append(tile_report)
        write_json(report_path, {"status": "running", "tiles": reports, "output": str(output),
                                                                        "grid": str(source_grid), "buffer_m": args.buffer_m})
    result = {"status": "completed", "output": str(output), "grid": str(source_grid), "buffer_m": args.buffer_m,
              "required_buffer_m": args.required_buffer_m, "tile_count": len(tiles), "tiles": reports,
              "method": "InVEST Habitat Quality tiled convolution with core-cell mosaic"}
    write_json(report_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datastack", type=Path, required=True)
    parser.add_argument("--invest-exe", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tiles-x", type=int, default=3)
    parser.add_argument("--tiles-y", type=int, default=3)
    parser.add_argument("--buffer-m", type=float, default=3000.0)
    parser.add_argument("--required-buffer-m", type=float, default=3000.0)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--invest-cli-profile", choices=("legacy_3_12", "modern_3_18"), default="modern_3_18",
                        help="Use modern_3_18 for the installed Workbench CLI; legacy_3_12 retains old input headers.")
    parser.add_argument("--resume", action="store_true", help="Continue a prior tiled run, retaining tiles recorded as completed.")
    parsed = parser.parse_args()
    print(json.dumps(run(parsed), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
