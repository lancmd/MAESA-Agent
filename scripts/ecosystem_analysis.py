#!/usr/bin/env python3
"""CLI entry points for ecosystem-service sub-analyses used by project workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ecosystem_service import geodetector_factor_analysis, scenario_compare, sensitivity_analysis, tradeoff_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    tradeoff = sub.add_parser("tradeoff")
    tradeoff.add_argument("--table", required=True, type=Path); tradeoff.add_argument("--fields", required=True)
    tradeoff.add_argument("--output", required=True, type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("--table", required=True, type=Path); compare.add_argument("--reference", required=True)
    compare.add_argument("--scenario-field", default="scenario"); compare.add_argument("--fields", required=True)
    compare.add_argument("--output", required=True, type=Path)
    sensitivity = sub.add_parser("sensitivity")
    sensitivity.add_argument("--table", required=True, type=Path); sensitivity.add_argument("--config", required=True, type=Path)
    sensitivity.add_argument("--relative-delta", type=float, default=0.1); sensitivity.add_argument("--output", required=True, type=Path)
    geodetector = sub.add_parser("geodetector")
    geodetector.add_argument("--table", required=True, type=Path); geodetector.add_argument("--target", required=True)
    geodetector.add_argument("--fields", required=True); geodetector.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "tradeoff":
        report = tradeoff_analysis(args.table, [value for value in args.fields.split(",") if value], args.output)
    elif args.action == "compare":
        report = scenario_compare(args.table, args.scenario_field, args.reference,
                                  [value for value in args.fields.split(",") if value], args.output)
    elif args.action == "sensitivity":
        report = sensitivity_analysis(args.table, args.config, args.relative_delta, args.output)
    else:
        report = geodetector_factor_analysis(args.table, args.target,
                                             [value for value in args.fields.split(",") if value], args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
