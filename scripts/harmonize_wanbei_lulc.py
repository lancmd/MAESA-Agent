#!/usr/bin/env python3
"""Build a comparable five-period, six-class LULC series for Wanbei mines.

The previous series was spatially aligned but its class *meaning* drifted
between years.  This tool keeps the MAESA six-class contract while separating
three roles that must not be confused:

* annual CLCD products provide a dated, independent semantic reference;
* the supplied image is used to refine the reference to the project grid;
* the supplied ROI is only a local reference for the subsidence-water split,
  never an accuracy claim or a source of forced class labels.

All output rasters use one EPSG:32650 30 m grid and one mine-boundary mask.
The final code contract is fixed: 1 subsidence water, 2 natural water,
3 built-up, 4 cropland, 5 forest, 6 grassland.  The processing report retains
``pending_independent_validation`` until temporally independent reference
samples are supplied.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
import shapefile  # pyshp
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from scipy.ndimage import distance_transform_edt
from sklearn.ensemble import RandomForestClassifier


YEARS = (2005, 2010, 2015, 2020, 2025)
CLASS_NAMES = {
    1: "subsidence_water",
    2: "natural_water",
    3: "built_up",
    4: "cropland",
    5: "forest",
    6: "grassland",
}
CLCD_RECORD_2023 = "12779975"
CLCD_RECORD_2024 = "15853565"


def same_grid(left: rasterio.DatasetReader, right: rasterio.DatasetReader) -> bool:
    return (
        left.crs == right.crs
        and left.width == right.width
        and left.height == right.height
        and left.transform.almost_equals(right.transform)
    )


def require_file(path: Path, description: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    return path


def clcd_url(year: int) -> tuple[str, int]:
    """Return the stable COG endpoint and source year used for a target year."""
    if year == 2025:
        return (
            f"https://zenodo.org/api/records/{CLCD_RECORD_2024}/files/CLCD_v01_2024_albert.tif/content",
            2024,
        )
    return (
        f"https://zenodo.org/api/records/{CLCD_RECORD_2023}/files/CLCD_v01_{year}_albert.tif/content",
        year,
    )


def to_six_classes(clcd: np.ndarray) -> np.ndarray:
    """Map the documented nine CLCD classes to the project-wide six classes."""
    result = np.zeros(clcd.shape, dtype=np.uint8)
    result[clcd == 1] = 4  # cropland
    result[clcd == 2] = 5  # forest
    result[np.isin(clcd, (3, 4, 6, 7))] = 6  # shrub/grass/snow/barren -> grassland
    result[np.isin(clcd, (5, 9))] = 2  # water/wetland are split later
    result[clcd == 8] = 3  # impervious
    return result


def shapes_on_grid(path: Path, crs: CRS) -> list[dict]:
    """Read a vector boundary and transform its geometry to the analysis CRS."""
    require_file(path, "Vector boundary")
    prj = path.with_suffix(".prj")
    require_file(prj, "Vector projection")
    source_crs = CRS.from_wkt(prj.read_text(encoding="utf-8", errors="ignore"))
    reader = shapefile.Reader(str(path))
    geometries: list[dict] = []
    for feature in reader.shapes():
        geometry = feature.__geo_interface__
        geometries.append(transform_geom(source_crs, crs, geometry, precision=8))
    if not geometries:
        raise ValueError(f"No geometries found in {path}")
    return geometries


def shape_mask(path: Path, profile: dict, *, invert: bool = True) -> np.ndarray:
    geometries = shapes_on_grid(path, CRS.from_user_input(profile["crs"]))
    return geometry_mask(
        geometries,
        transform=profile["transform"],
        out_shape=(profile["height"], profile["width"]),
        invert=invert,
        all_touched=False,
    )


def read_clcd_to_grid(url: str, profile: dict) -> np.ndarray:
    """Read only the reprojected study-grid cells from a remote COG."""
    with rasterio.open(url) as source:
        with WarpedVRT(
            source,
            crs=profile["crs"],
            transform=profile["transform"],
            width=profile["width"],
            height=profile["height"],
            resampling=Resampling.nearest,
            nodata=0,
        ) as vrt:
            return vrt.read(1).astype(np.uint8, copy=False)


def read_feature_block(dataset: rasterio.DatasetReader, year: int, window: rasterio.windows.Window) -> np.ndarray:
    """Build image features on the fixed 30 m target grid for one window."""
    height, width = int(window.height), int(window.width)
    if year < 2020:
        raw = dataset.read(list(range(1, min(dataset.count, 7) + 1)), window=window).astype(np.float32)
        if raw.shape[0] < 4:
            raise ValueError(f"{year} imagery requires at least four spectral bands")
        blue, green, red, nir = raw[0], raw[1], raw[2], raw[3]
        swir1 = raw[4] if raw.shape[0] > 4 else nir
        ndvi = (nir - red) / (nir + red + 1e-6)
        ndwi = (green - nir) / (green + nir + 1e-6)
        ndbi = (swir1 - nir) / (swir1 + nir + 1e-6)
        return np.moveaxis(np.concatenate((raw, ndvi[None], ndwi[None], ndbi[None]), axis=0), 0, -1)

    # Sentinel-2 imagery is 10 m and has RGB only.  Average the matching 3 x 3
    # pixels onto the 30 m master grid; this is a feature transformation only,
    # never interpolation of the final categorical map.
    source_window = rasterio.windows.Window(
        int(window.col_off) * 3,
        int(window.row_off) * 3,
        width * 3,
        height * 3,
    )
    raw = dataset.read(
        [1, 2, 3],
        window=source_window,
        out_shape=(3, height, width),
        resampling=Resampling.average,
    ).astype(np.float32)
    red, green, blue = raw[0], raw[1], raw[2]
    green_red = (green - red) / (green + red + 1e-6)
    blue_red = (blue - red) / (blue + red + 1e-6)
    intensity = (red + green + blue) / 3.0
    return np.moveaxis(np.concatenate((raw, green_red[None], blue_red[None], intensity[None]), axis=0), 0, -1)


def windows_for(profile: dict, rows: int) -> Iterable[rasterio.windows.Window]:
    for row in range(0, profile["height"], rows):
        yield rasterio.windows.Window(0, row, profile["width"], min(rows, profile["height"] - row))


def valid_feature_rows(features: np.ndarray) -> np.ndarray:
    flat = features.reshape(-1, features.shape[-1])
    return np.all(np.isfinite(flat), axis=1) & (np.max(np.abs(flat), axis=1) < 1e6) & (np.any(np.abs(flat) > 1e-6, axis=1))


def collect_training(
    dataset: rasterio.DatasetReader,
    year: int,
    semantic: np.ndarray,
    mine: np.ndarray,
    profile: dict,
    rng: np.random.Generator,
    per_class: int,
    rows: int,
) -> tuple[np.ndarray, np.ndarray, dict[int, int]]:
    samples: dict[int, list[np.ndarray]] = {code: [] for code in (2, 3, 4, 5, 6)}
    remaining = {code: per_class for code in samples}
    for window in windows_for(profile, rows):
        r0, r1 = int(window.row_off), int(window.row_off + window.height)
        labels = semantic[r0:r1, :].reshape(-1)
        eligible = mine[r0:r1, :].reshape(-1)
        if not np.any(eligible & (labels > 0)):
            continue
        features = read_feature_block(dataset, year, window)
        flat = features.reshape(-1, features.shape[-1])
        valid = valid_feature_rows(features) & eligible
        for code in samples:
            if remaining[code] <= 0:
                continue
            index = np.flatnonzero(valid & (labels == code))
            if not len(index):
                continue
            # Retain representation along the full study area, not a single
            # block.  A cap per block prevents the first large cropland block
            # from dominating the local semantic model.
            take = min(remaining[code], len(index), 450)
            chosen = rng.choice(index, size=take, replace=False)
            samples[code].append(flat[chosen])
            remaining[code] -= take
    feature_rows: list[np.ndarray] = []
    label_rows: list[np.ndarray] = []
    counts: dict[int, int] = {}
    for code, chunks in samples.items():
        if not chunks:
            continue
        values = np.concatenate(chunks, axis=0)
        feature_rows.append(values)
        label_rows.append(np.full(len(values), code, dtype=np.uint8))
        counts[code] = len(values)
    if len(feature_rows) < 2:
        raise RuntimeError(f"{year}: insufficient semantic-reference samples for local refinement: {counts}")
    return np.concatenate(feature_rows), np.concatenate(label_rows), counts


def profile_for_output(master: rasterio.DatasetReader) -> dict:
    profile = master.profile.copy()
    profile.update(
        dtype="uint8",
        count=1,
        nodata=0,
        compress="deflate",
        predictor=2,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    return profile


def water_split(
    year: int,
    high_level: np.ndarray,
    old_lulc: np.ndarray | None,
    depth: np.ndarray | None,
    distance_to_workface_m: np.ndarray | None,
) -> np.ndarray:
    """Split semantically confirmed water without adding a seventh final class."""
    result = high_level.copy()
    water = result == 2
    sink = np.zeros(result.shape, dtype=bool)
    # Existing output is deliberately not trusted for its land/vegetation
    # labels.  Its code 1 is nevertheless used only as a local *candidate* for
    # the two water subclasses, and only after the new map confirms water.
    if old_lulc is not None:
        sink |= water & (old_lulc == 1)
    # The 2025 depth surface and the matching workface layout are the strongest
    # project-specific evidence.  A 0.20 m threshold sits between the supplied
    # 2025 natural-water and subsidence-water ROI medians; it is not applied to
    # terrestrial pixels or retroactively to historic maps.
    if year == 2025 and depth is not None and distance_to_workface_m is not None:
        sink |= water & (depth >= 0.20) & (distance_to_workface_m <= 8000.0)
    result[sink] = 1
    return result


def roi_water_labels(path: Path, profile: dict) -> np.ndarray:
    """Rasterize only the two water ROI labels onto the analysis grid.

    Other ROI classes are intentionally excluded.  The water ROIs are a local
    cue for distinguishing two water subclasses after the semantic reference
    has already identified water; they are not global labels and are not used
    for an accuracy statement.
    """
    labels = np.zeros((profile["height"], profile["width"]), dtype=np.uint8)
    if not path.is_file():
        return labels
    root = ET.parse(path).getroot()
    crs_text = next((node.text for node in root.findall(".//CoordSysStr") if node.text and node.text.strip()), None)
    if not crs_text:
        return labels
    source_crs = CRS.from_wkt(crs_text)
    targets = (("沉陷", 1), ("自然水", 2))
    for region in root.findall("Region"):
        name = (region.attrib.get("name") or "").strip()
        code = next((value for token, value in targets if token in name), None)
        if code is None:
            continue
        geometries: list[dict] = []
        for polygon in region.findall(".//Polygon"):
            node = polygon.find(".//Coordinates")
            if node is None or not node.text:
                continue
            values = [float(value) for value in node.text.split()]
            if len(values) < 6 or len(values) % 2:
                continue
            ring = list(zip(values[::2], values[1::2]))
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            geometries.append(transform_geom(source_crs, profile["crs"], {"type": "Polygon", "coordinates": [ring]}, precision=8))
        if geometries:
            labels[geometry_mask(geometries, transform=profile["transform"], out_shape=labels.shape, invert=True)] = code
    return labels


def refine_water_with_roi(
    image_path: Path,
    year: int,
    high_level: np.ndarray,
    mine: np.ndarray,
    profile: dict,
    roi_labels: np.ndarray,
    depth: np.ndarray | None,
    rng: np.random.Generator,
    workers: int,
    trees: int,
    confidence: float,
) -> tuple[np.ndarray, dict | None]:
    """Apply a small local water-subtype model, only where water is confirmed."""
    if not np.any(roi_labels == 1) or not np.any(roi_labels == 2):
        return high_level, None

    samples: dict[int, list[np.ndarray]] = {1: [], 2: []}
    with rasterio.open(image_path) as image:
        for window in windows_for(profile, 128):
            r0, r1 = int(window.row_off), int(window.row_off + window.height)
            local_roi = roi_labels[r0:r1, :]
            if not np.any(local_roi):
                continue
            features = read_feature_block(image, year, window)
            if year == 2025 and depth is not None:
                local_depth = np.nan_to_num(depth[r0:r1, :], nan=-1.0, posinf=-1.0, neginf=-1.0)
                features = np.concatenate((features, local_depth[..., None]), axis=2)
            flat = features.reshape(-1, features.shape[-1])
            valid = valid_feature_rows(features) & mine[r0:r1, :].reshape(-1)
            labels = local_roi.reshape(-1)
            for code in (1, 2):
                index = np.flatnonzero(valid & (labels == code))
                if len(index):
                    take = min(len(index), 450)
                    samples[code].append(flat[rng.choice(index, size=take, replace=False)])
        if not samples[1] or not samples[2]:
            return high_level, None
        x_train = np.concatenate((np.concatenate(samples[1]), np.concatenate(samples[2])))
        y_train = np.concatenate((np.ones(sum(len(v) for v in samples[1]), dtype=np.uint8), np.full(sum(len(v) for v in samples[2]), 2, dtype=np.uint8)))
        model = RandomForestClassifier(
            n_estimators=max(80, trees // 2), min_samples_leaf=2, max_features="sqrt",
            class_weight="balanced_subsample", n_jobs=workers, random_state=year + 100,
        )
        model.fit(x_train, y_train)
        result = high_level.copy()
        refined = 0
        for window in windows_for(profile, 128):
            r0, r1 = int(window.row_off), int(window.row_off + window.height)
            features = read_feature_block(image, year, window)
            if year == 2025 and depth is not None:
                local_depth = np.nan_to_num(depth[r0:r1, :], nan=-1.0, posinf=-1.0, neginf=-1.0)
                features = np.concatenate((features, local_depth[..., None]), axis=2)
            flat = features.reshape(-1, features.shape[-1])
            target = result[r0:r1, :].reshape(-1)
            use = valid_feature_rows(features) & (target == 2) & mine[r0:r1, :].reshape(-1)
            if not np.any(use):
                continue
            probability = model.predict_proba(flat[use])
            predict = model.classes_[np.argmax(probability, axis=1)].astype(np.uint8)
            certain = np.max(probability, axis=1) >= confidence
            index = np.flatnonzero(use)[certain]
            target[index] = predict[certain]
            refined += int(np.count_nonzero(certain))
            result[r0:r1, :] = target.reshape(result[r0:r1, :].shape)
    return result, {
        "roi_role": "local_water_subtype_reference_only",
        "roi_samples": {"subsidence_water": int(sum(len(v) for v in samples[1])), "natural_water": int(sum(len(v) for v in samples[2]))},
        "water_pixels_refined_from_roi_pattern": refined,
        "confidence_threshold": confidence,
    }


def class_counts(array: np.ndarray, mine: np.ndarray) -> dict[int, int]:
    return {code: int(np.count_nonzero((array == code) & mine)) for code in range(1, 7)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Wanbei project folder")
    parser.add_argument("--output-dir", help="New output directory; existing final_grid_v3 is never overwritten")
    parser.add_argument("--trees", type=int, default=120)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--training-per-class", type=int, default=12000)
    parser.add_argument("--confidence", type=float, default=0.55, help="Below this, retain the semantic reference")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 0.0 < args.confidence < 1.0:
        parser.error("--confidence must be between 0 and 1")
    root = Path(args.root).expanduser().resolve()
    output = (Path(args.output_dir).expanduser().resolve() if args.output_dir else root / "outputs" / "classification" / "harmonized_clcd_v1")
    if output.exists() and any(output.iterdir()) and not args.overwrite:
        raise FileExistsError(f"Refusing to overwrite existing harmonized output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    master_path = require_file(root / "imagery" / "2005.tif", "2005 master imagery")
    boundary = require_file(root / "boundaries" / "mine_boundary.shp", "Mine boundary")
    old_dir = root / "outputs" / "classification" / "final_grid_v3"
    depth_path = root / "subsidence" / "aligned" / "subsidence_depth_2025_positive_down_30m_utm50n.tif"
    workface_path = root / "boundaries" / "workface_2025.shp"

    with rasterio.open(master_path) as master:
        grid = {"crs": master.crs, "transform": master.transform, "width": master.width, "height": master.height}
        write_profile = profile_for_output(master)
        mine = shape_mask(boundary, grid)
    cell_area_ha = abs(grid["transform"].a * grid["transform"].e) / 10000.0
    np.save(output / "mine_boundary_mask_30m.npy", mine)

    depth: np.ndarray | None = None
    distance_to_workface: np.ndarray | None = None
    if depth_path.is_file() and workface_path.is_file():
        with rasterio.open(depth_path) as source:
            if not (source.crs == grid["crs"] and source.width == grid["width"] and source.height == grid["height"] and source.transform.almost_equals(grid["transform"])):
                raise RuntimeError("2025 subsidence depth is not aligned to the 30 m analysis grid")
            depth = source.read(1).astype(np.float32)
            if source.nodata is not None:
                depth[depth == source.nodata] = np.nan
        workface = shape_mask(workface_path, grid)
        distance_to_workface = distance_transform_edt(~workface) * abs(grid["transform"].a)

    semantic_by_year: dict[int, np.ndarray] = {}
    source_meta: dict[int, dict] = {}
    for year in YEARS:
        url, source_year = clcd_url(year)
        raw = read_clcd_to_grid(url, grid)
        semantic = to_six_classes(raw)
        semantic[~mine] = 0
        semantic_by_year[year] = semantic
        source_meta[year] = {"source_year": source_year, "url": url, "clcd_codes_found": sorted(int(x) for x in np.unique(raw[mine]))}

    rows: list[dict] = []
    period_reports: list[dict] = []
    rng = np.random.default_rng(20260901)
    for year in YEARS:
        image_path = require_file(root / "imagery" / f"{year}.tif", f"{year} imagery")
        old_path = old_dir / f"LULC_{year}_30m_masked.tif"
        old_lulc: np.ndarray | None = None
        if old_path.is_file():
            with rasterio.open(old_path) as old:
                if not (old.crs == grid["crs"] and old.width == grid["width"] and old.height == grid["height"] and old.transform.almost_equals(grid["transform"])):
                    raise RuntimeError(f"Existing {year} LULC does not match the master grid")
                old_lulc = old.read(1).astype(np.uint8)

        with rasterio.open(image_path) as image:
            # 2020/2025 are exact 3x 10 m versions of the fixed 30 m grid;
            # older imagery already uses the target grid.
            if year < 2020 and not (
                image.crs == grid["crs"]
                and image.width == grid["width"]
                and image.height == grid["height"]
                and image.transform.almost_equals(grid["transform"])
            ):
                raise RuntimeError(f"{year} imagery does not match the master grid")
            if year >= 2020 and (image.width != grid["width"] * 3 or image.height != grid["height"] * 3 or image.crs != grid["crs"]):
                raise RuntimeError(f"{year} imagery must be an exact 10 m 3x version of the master grid")
            x_train, y_train, training_counts = collect_training(
                image, year, semantic_by_year[year], mine, grid, rng, args.training_per_class, 128
            )
            model = RandomForestClassifier(
                n_estimators=args.trees,
                min_samples_leaf=2,
                max_features="sqrt",
                class_weight="balanced_subsample",
                n_jobs=args.workers,
                random_state=year,
            )
            model.fit(x_train, y_train)
            final = semantic_by_year[year].copy()
            confidence_samples: list[np.ndarray] = []
            refined_pixels = 0
            fallback_pixels = 0
            for window in windows_for(grid, 128):
                r0, r1 = int(window.row_off), int(window.row_off + window.height)
                local_semantic = semantic_by_year[year][r0:r1, :]
                local_mine = mine[r0:r1, :]
                features = read_feature_block(image, year, window)
                flat = features.reshape(-1, features.shape[-1])
                valid = valid_feature_rows(features)
                target = local_semantic.reshape(-1).copy()
                use = valid & local_mine.reshape(-1) & (target > 0)
                if np.any(use):
                    probability = model.predict_proba(flat[use])
                    prediction = model.classes_[np.argmax(probability, axis=1)].astype(np.uint8)
                    certainty = np.max(probability, axis=1)
                    refine = certainty >= args.confidence
                    target_index = np.flatnonzero(use)
                    target[target_index[refine]] = prediction[refine]
                    refined_pixels += int(np.count_nonzero(refine))
                    fallback_pixels += int(np.count_nonzero(~refine))
                    confidence_samples.append(certainty[::max(1, len(certainty) // 5000)])
                final[r0:r1, :] = target.reshape(local_semantic.shape)

        water_roi_report: dict | None = None
        if year in (2020, 2025):
            final, water_roi_report = refine_water_with_roi(
                image_path,
                year,
                final,
                mine,
                grid,
                roi_water_labels(root / "roi" / f"roi{year}.xml", grid),
                depth,
                rng,
                args.workers,
                args.trees,
                max(args.confidence, 0.60),
            )
        final = water_split(year, final, old_lulc, depth, distance_to_workface)
        final[~mine] = 0
        output_raster = output / f"LULC_{year}_30m_masked.tif"
        with rasterio.open(output_raster, "w", **write_profile) as destination:
            destination.write(final, 1)
            destination.update_tags(
                class_contract="1=subsidence_water;2=natural_water;3=built_up;4=cropland;5=forest;6=grassland",
                semantic_reference="CLCD annual land-cover product",
                roi_role="local_reference_only_not_accuracy_evidence",
                accuracy_status="pending_independent_validation",
            )
        counts = class_counts(final, mine)
        for code, count in counts.items():
            rows.append({"year": year, "lucode": code, "landuse": CLASS_NAMES[code], "pixel_count": count, "area_ha": round(count * cell_area_ha, 6)})
        confidence = np.concatenate(confidence_samples) if confidence_samples else np.array([], dtype=float)
        period_reports.append(
            {
                "year": year,
                "image": str(image_path),
                "output": str(output_raster),
                "semantic_reference": source_meta[year],
                "training_samples_by_class": training_counts,
                "mean_model_confidence_for_reference_refinement": round(float(confidence.mean()), 6) if len(confidence) else None,
                "pixels_refined_from_semantic_reference": refined_pixels,
                "pixels_retained_as_semantic_reference": fallback_pixels,
                "water_split": "old_code_1_candidate_intersected_with_semantically_confirmed_water" + (";plus_2025_depth>=0.20m_and_workface_distance<=8km" if year == 2025 else ""),
                "water_roi_refinement": water_roi_report,
                "final_counts": counts,
            }
        )
        print(json.dumps({"year": year, "counts": counts, "output": str(output_raster)}, ensure_ascii=False), flush=True)

    with (output / "landuse_area_statistics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["year", "lucode", "landuse", "pixel_count", "area_ha"])
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "status": "completed_with_pending_independent_validation",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "annual_semantic_reference_plus_local_image_refinement_on_common_30m_grid",
        "final_class_contract": {str(k): v for k, v in CLASS_NAMES.items()},
        "roi_role": "reference_only; not assumed correct; not used to publish accuracy",
        "external_reference_role": "annual semantic reference; not a field-validation substitute",
        "accuracy_status": "pending_independent_validation",
        "analysis_grid": {"crs": str(grid["crs"]), "width": grid["width"], "height": grid["height"], "transform": list(grid["transform"]), "cell_area_ha": cell_area_ha},
        "common_statistical_mask_pixels": int(np.count_nonzero(mine)),
        "common_statistical_area_ha": round(float(np.count_nonzero(mine) * cell_area_ha), 6),
        "periods": period_reports,
        "outputs": {"area_statistics": str(output / "landuse_area_statistics.csv"), "mask": str(output / "mine_boundary_mask_30m.npy")},
    }
    (output / "lulc_harmonization_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "area_statistics": report["outputs"]["area_statistics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
