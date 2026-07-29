#!/usr/bin/env python3
"""Inspect ROI sample coverage before local supervised classification.

This is deliberately a sample-design check, not an accuracy assessment.  It
counts labelled training/validation features, looks for missing classes and
obvious duplicate geometries, and records when independence still needs human
review.  It never converts a large contiguous polygon into a false count of
independent observations.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _json_geometry(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _geojson(path: Path) -> tuple[list[dict[str, Any]], str | None, str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("GeoJSON ROI input must be a FeatureCollection")
    crs = payload.get("crs")
    if isinstance(crs, dict):
        properties = crs.get("properties")
        crs_name = properties.get("name") if isinstance(properties, dict) else None
    else:
        crs_name = None
    features = []
    for index, feature in enumerate(payload["features"]):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"GeoJSON feature {index} is not a Feature")
        props = feature.get("properties")
        features.append({"properties": props if isinstance(props, dict) else {}, "geometry": feature.get("geometry")})
    return features, crs_name, "geojson"


def _csv(path: Path) -> tuple[list[dict[str, Any]], str | None, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("ROI CSV contains no records")
    return [{"properties": dict(row), "geometry": None} for row in rows], None, "csv"


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _envi_xml(path: Path) -> tuple[list[dict[str, Any]], str | None, str]:
    """Read ENVI XML ROIs without pretending that Region names are a split.

    ENVI writes one or more ``Polygon`` nodes inside each named ``Region``.
    Each polygon is a sample feature for coverage counts.  The precise vertex
    dialect varies across ENVI versions, so geometry is intentionally omitted
    here; pixel/feature overlap must be checked in ENVI or after exporting a
    vector ROI layer.  Both ``name`` and ``class_id`` expose the Region name
    so a user can select either field in the MCP tool.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"invalid ENVI ROI XML: {error}") from error
    if _local_name(root) != "RegionsOfInterest":
        raise ValueError("ENVI ROI XML root must be RegionsOfInterest")
    features: list[dict[str, Any]] = []
    unnamed = 0
    for region in (item for item in root.iter() if _local_name(item) == "Region"):
        name = str(region.attrib.get("name", "")).strip()
        if not name:
            name = f"unnamed_region_{unnamed + 1}"
            unnamed += 1
        polygons = [item for item in region.iter() if _local_name(item) == "Polygon"]
        for _ in polygons:
            features.append({"properties": {"class_id": name, "name": name}, "geometry": None})
    if not features:
        raise ValueError("ENVI ROI XML contains no Region Polygon elements")
    return features, None, "envi_roi_xml"


def _fiona(path: Path) -> tuple[list[dict[str, Any]], str | None, str]:
    try:
        import fiona  # type: ignore
    except ImportError as error:
        raise RuntimeError("GPKG/Shapefile ROI input needs Fiona or a local ArcGIS Pro Python runtime") from error
    with fiona.open(path) as source:
        features = [{"properties": dict(item.get("properties") or {}), "geometry": item.get("geometry")}
                    for item in source]
        crs = str(source.crs_wkt or source.crs) if source.crs_wkt or source.crs else None
    return features, crs, "fiona"


def _arcgis_read(path: Path, class_field: str, role_field: str | None) -> tuple[list[dict[str, Any]], str | None, str]:
    """Fallback for .gpkg/.shp installations where ArcGIS Pro is available.

    The current script runs once under ``propy`` and returns a JSON-only
    feature summary, so it does not turn the MCP server into a remote ArcGIS
    control service.
    """
    try:
        from workflow_agent import probe_software
    except ImportError as error:
        raise RuntimeError("cannot locate the local ArcGIS Pro Python bridge") from error
    propy = probe_software()["software"]["arcgis_propy"].get("path")
    if not propy:
        raise RuntimeError("GPKG/Shapefile ROI input needs Fiona or configured ArcGIS Pro Python")
    command = [str(propy), str(Path(__file__).resolve()), "--arcgis-read", str(path), "--class-field", class_field]
    if role_field:
        command.extend(["--role-field", role_field])
    process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             encoding="utf-8", errors="replace", check=False)
    if process.returncode:
        raise RuntimeError("ArcGIS ROI read failed: " + (process.stderr or process.stdout).strip())
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("ArcGIS ROI read returned invalid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RuntimeError("ArcGIS ROI read returned no feature list")
    return payload["features"], payload.get("crs"), "arcgis_propy"


def _read_with_arcpy(path: Path, class_field: str, role_field: str | None) -> int:
    """Internal ``propy`` entry point; kept separate from normal CLI parsing."""
    import arcpy  # type: ignore

    described = arcpy.Describe(str(path))
    field_names = {field.name.lower(): field.name for field in arcpy.ListFields(str(path))}
    for name in (class_field, role_field):
        if name and name.lower() not in field_names:
            raise ValueError(f"ROI field is missing: {name}")
    fields = [field_names[class_field.lower()]]
    if role_field:
        fields.append(field_names[role_field.lower()])
    fields.append("SHAPE@")
    features: list[dict[str, Any]] = []
    with arcpy.da.SearchCursor(str(path), fields) as cursor:
        for row in cursor:
            properties = {class_field: row[0]}
            geometry_index = 1
            if role_field:
                properties[role_field] = row[1]
                geometry_index = 2
            geometry = row[geometry_index]
            features.append({"properties": properties, "geometry": json.loads(geometry.JSON) if geometry else None})
    spatial_reference = getattr(described, "spatialReference", None)
    crs = spatial_reference.exportToString() if spatial_reference and spatial_reference.name not in {"Unknown", ""} else None
    print(json.dumps({"features": features, "crs": crs}, ensure_ascii=False))
    return 0


def read_features(path: Path, class_field: str, role_field: str | None) -> tuple[list[dict[str, Any]], str | None, str]:
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        return _geojson(path)
    if suffix == ".csv":
        return _csv(path)
    if suffix == ".xml":
        return _envi_xml(path)
    try:
        return _fiona(path)
    except RuntimeError:
        return _arcgis_read(path, class_field, role_field)


def _geometry_key(geometry: Any) -> str | None:
    parsed = _json_geometry(geometry)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")) if parsed else None


def _intersections(training: list[dict[str, Any]], validation: list[dict[str, Any]]) -> tuple[int | None, str]:
    """Return exact/real geometry overlaps and state the level of certainty."""
    training_geometries = [_json_geometry(item.get("geometry")) for item in training]
    validation_geometries = [_json_geometry(item.get("geometry")) for item in validation]
    if not any(training_geometries) or not any(validation_geometries):
        return None, "not_available_no_geometries"
    try:
        from shapely.geometry import shape  # type: ignore
    except ImportError:
        left = {key for item in training_geometries if (key := _geometry_key(item))}
        exact = sum(1 for item in validation_geometries if (key := _geometry_key(item)) in left)
        return exact, "exact_geometry_only"
    left_shapes = [shape(item) for item in training_geometries if item]
    count = 0
    for item in validation_geometries:
        if item and any(shape(item).intersects(candidate) for candidate in left_shapes):
            count += 1
    return count, "geometry_intersection"


def inspect(path: Path, class_field: str, *, role_field: str | None = None,
            training_value: str = "training", validation_value: str = "validation",
            expected_classes: list[str | int] | None = None, minimum_rois_per_class: int = 30,
            max_class_imbalance_ratio: float = 10.0, sample_count_field: str | None = None,
            require_training_only: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"ROI input does not exist: {path}")
    if not class_field.strip():
        raise ValueError("class_field must be a non-empty string")
    if minimum_rois_per_class < 1:
        raise ValueError("minimum_rois_per_class must be at least 1")
    if max_class_imbalance_ratio < 1:
        raise ValueError("max_class_imbalance_ratio must be at least 1")
    features, crs, reader = read_features(path.resolve(), class_field, role_field)
    errors: list[str] = []
    warnings: list[str] = []
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_class = 0
    for feature in features:
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        value = properties.get(class_field)
        label = str(value).strip() if value is not None else ""
        if not label:
            missing_class += 1
            continue
        item = {"properties": properties, "geometry": feature.get("geometry"), "label": label}
        by_class[label].append(item)
        if role_field:
            role_value = properties.get(role_field)
            role = str(role_value).strip() if role_value is not None else ""
            if role:
                by_role[role].append(item)
    if not features:
        errors.append("ROI input contains no features")
    if missing_class:
        errors.append(f"{missing_class} ROI features have an empty {class_field} value")
    if not by_class:
        errors.append("ROI input contains no labelled sample features")
    counts = {label: len(items) for label, items in sorted(by_class.items())}
    underrepresented = sorted(label for label, count in counts.items() if count < minimum_rois_per_class)
    if underrepresented:
        warnings.append("classes below the requested ROI-count guidance: " + ", ".join(underrepresented))
    required = {str(item).strip() for item in expected_classes or []}
    missing_expected = sorted(required - set(counts))
    if missing_expected:
        errors.append("expected classes absent from ROI input: " + ", ".join(missing_expected))
    declared_fields = {str(key) for feature in features
                       for key in (feature.get("properties") or {}).keys()}
    if class_field not in declared_fields:
        errors.append(f"ROI class field is missing: {class_field}")
    if len(counts) < 2:
        errors.append("ROI input needs at least two labelled classes")
    vector_reader = reader in {"geojson", "fiona", "arcgis_propy"}
    if vector_reader and not crs:
        errors.append("ROI CRS is not declared")
    elif not crs:
        warnings.append("ROI CRS is not declared; verify that the layer will be transformed to the imagery CRS")
    if vector_reader:
        geometries = [_json_geometry(item.get("geometry")) for item in features]
        missing_geometry = sum(item is None for item in geometries)
        if missing_geometry:
            errors.append(f"{missing_geometry} ROI features have no valid geometry")
        else:
            try:
                from shapely.geometry import shape  # type: ignore
                invalid_geometry = sum(not shape(item).is_valid for item in geometries if item)
            except ImportError:
                warnings.append("Shapely is unavailable; ROI geometry validity was not checked")
            except (TypeError, ValueError):
                errors.append("ROI contains a geometry that cannot be read")
            else:
                if invalid_geometry:
                    errors.append(f"{invalid_geometry} ROI geometries are invalid")
    if counts:
        smallest, largest = min(counts.values()), max(counts.values())
        if smallest and largest / smallest > max_class_imbalance_ratio:
            warnings.append(f"class ROI-count imbalance exceeds {max_class_imbalance_ratio:g}:1")
    pixel_totals: dict[str, float] = {}
    if sample_count_field:
        invalid_samples = 0
        for label, rows in by_class.items():
            total = 0.0
            for item in rows:
                try:
                    total += float(item["properties"].get(sample_count_field, 0))
                except (TypeError, ValueError):
                    invalid_samples += 1
            pixel_totals[label] = total
        if invalid_samples:
            warnings.append(f"{invalid_samples} ROI features have a non-numeric {sample_count_field} value")
    roles = {key: len(value) for key, value in sorted(by_role.items())}
    validation_status = "pending_validation"
    overlap_count: int | None = None
    overlap_check = "not_requested"
    if role_field:
        training = by_role.get(training_value, [])
        validation = by_role.get(validation_value, [])
        if require_training_only:
            unexpected_roles = {role: count for role, count in roles.items() if role != training_value}
            if not training:
                errors.append(f"training ROI has no {training_value!r} samples in {role_field}")
            if unexpected_roles:
                detail = ", ".join(f"{role}={count}" for role, count in sorted(unexpected_roles.items()))
                errors.append("training ROI contains non-training role samples that ENVI would also use: " + detail)
        if not training:
            warnings.append(f"no {training_value!r} samples found in {role_field}")
        if not validation:
            warnings.append(f"no independent {validation_value!r} samples found in {role_field}")
        if training and validation:
            overlap_count, overlap_check = _intersections(training, validation)
            if overlap_count:
                errors.append(f"{overlap_count} validation ROI geometries overlap training ROI geometries")
            else:
                validation_status = "completed"
                if overlap_check == "exact_geometry_only":
                    warnings.append("only exact duplicate geometries were checked; inspect spatial separation before reporting accuracy")
                elif overlap_check.startswith("not_available"):
                    warnings.append("training/validation spatial separation could not be checked because geometry is unavailable")
    else:
        warnings.append("no role_field supplied; independent validation remains pending_validation")
    quality_status = "failed" if errors else "review" if warnings else "pass"
    return {
        "status": "failed" if errors else "completed",
        "quality_status": quality_status,
        "validation_status": validation_status,
        "roi_file": str(path.resolve()),
        "reader": reader,
        "crs": crs,
        "class_field": class_field,
        "role_field": role_field,
        "feature_count": len(features),
        "class_counts": counts,
        "class_pixel_count_totals": pixel_totals or None,
        "role_counts": roles or None,
        "minimum_rois_per_class": minimum_rois_per_class,
        "max_class_imbalance_ratio": max_class_imbalance_ratio,
        "training_validation_overlap_count": overlap_count,
        "training_validation_overlap_check": overlap_check,
        "training_only_enforced": require_training_only,
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "ROI feature count is not a substitute for independent pixel/sample count.",
            "Spectral purity, date consistency, and interpretive correctness need image-aware review.",
        ],
    }


def write_report(report: dict[str, Any], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(output.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--class-field", default="class_id")
    parser.add_argument("--role-field")
    parser.add_argument("--training-value", default="training")
    parser.add_argument("--validation-value", default="validation")
    parser.add_argument("--expected-class", action="append", default=[])
    parser.add_argument("--minimum-rois-per-class", type=int, default=30)
    parser.add_argument("--max-class-imbalance-ratio", type=float, default=10.0)
    parser.add_argument("--sample-count-field")
    parser.add_argument("--require-training-only", action="store_true",
                        help="fail when a role-labelled ENVI training ROI contains validation or other roles")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--arcgis-read", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.arcgis_read:
        return _read_with_arcpy(args.arcgis_read.expanduser().resolve(), args.class_field, args.role_field)
    if not args.roi or not args.output:
        parser.error("--roi and --output are required")
    report = inspect(args.roi.expanduser().resolve(), args.class_field, role_field=args.role_field,
                     training_value=args.training_value, validation_value=args.validation_value,
                     expected_classes=args.expected_class, minimum_rois_per_class=args.minimum_rois_per_class,
                     max_class_imbalance_ratio=args.max_class_imbalance_ratio,
                     sample_count_field=args.sample_count_field,
                     require_training_only=args.require_training_only)
    report["output"] = write_report(report, args.output.expanduser().resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
