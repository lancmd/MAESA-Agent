#!/usr/bin/env python3
"""Read raster values at ROI centroids for a transparent classification preflight."""

from __future__ import annotations

import argparse
import json
from collections import Counter

from osgeo import gdal, ogr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raster", required=True)
    parser.add_argument("--roi", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    raster = gdal.Open(args.raster, gdal.GA_ReadOnly)
    vector = ogr.Open(args.roi, 0)
    if raster is None or vector is None:
        raise RuntimeError("Raster or ROI cannot be opened")
    layer = vector.GetLayer(0)
    gt = raster.GetGeoTransform()
    counts: Counter[tuple[int, ...]] = Counter()
    per_class: dict[int, Counter[tuple[int, ...]]] = {}
    samples = []
    for index, feature in enumerate(layer):
        if index >= args.limit:
            break
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        point = geometry.Centroid()
        px = int((point.GetX() - gt[0]) / gt[1])
        py = int((gt[3] - point.GetY()) / (-gt[5]))
        if px < 0 or py < 0 or px >= raster.RasterXSize or py >= raster.RasterYSize:
            values = None
        else:
            values = tuple(
                int(raster.GetRasterBand(band).ReadAsArray(px, py, 1, 1)[0, 0])
                for band in range(1, raster.RasterCount + 1)
            )
        class_id = int(feature.GetField("class_id"))
        if values is not None:
            counts[values] += 1
            per_class.setdefault(class_id, Counter())[values] += 1
        samples.append({"class_id": class_id, "pixel": [px, py], "values": values})
    payload = {
        "raster_bands": raster.RasterCount,
        "samples_checked": len(samples),
        "value_patterns": {str(k): v for k, v in counts.most_common(20)},
        "by_class": {str(key): {str(k): v for k, v in value.items()} for key, value in per_class.items()},
        "samples": samples[:20],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
