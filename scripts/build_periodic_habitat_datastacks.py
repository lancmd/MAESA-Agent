#!/usr/bin/env python3
"""Build dated Habitat Quality datastacks from one parameter template.

Use ``{year}`` in any template string that should resolve to the dated input,
for example a cumulative mining-workface threat raster.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from invest_datastack_builder import build_habitat_quality_datastack


def _dated(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        year, marker, value = raw.partition("=")
        path = Path(value).expanduser().resolve()
        if not marker or not year.isdigit() or not path.is_file():
            raise ValueError(f"--lulc requires YEAR=EXISTING_PATH: {raw}")
        result[year] = path
    return result


def _substitute(value, year: str):
    if isinstance(value, str):
        return value.replace("{year}", year)
    if isinstance(value, list):
        return [_substitute(item, year) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, year) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--lulc", action="append", required=True, metavar="YEAR=PATH")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    template = args.template.resolve()
    payload = json.loads(template.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise SystemExit("template must be a JSON object")
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    records = []
    for year, lulc in sorted(_dated(args.lulc).items()):
        config = _substitute(copy.deepcopy(payload), year)
        config["lulc_path"] = str(lulc)
        build_dir = output / f"build_{year}"
        stack = output / f"habitat_quality_{year}.json"
        report = build_habitat_quality_datastack(config, build_dir, source_base=template.parent,
                                                  lulc_override=lulc, datastack_path=stack,
                                                  allow_overwrite=True)
        if report["status"] != "completed":
            raise RuntimeError(f"Habitat Quality datastack failed for {year}: {report['errors']}")
        records.append({"year": year, "datastack": str(stack), "builder_report": str(build_dir / "habitat_datastack_manifest.json")})
    manifest = {"status": "completed", "model": "habitat_quality", "records": records}
    (output / "habitat_quality_datastacks_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
