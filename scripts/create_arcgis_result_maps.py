#!/usr/bin/env python3
"""Create paper-style ArcGIS Pro map projects and exports from completed rasters.

ArcGIS Pro 3.0 cannot add a new layout to an ``.aprx`` through arcpy.mp.  This
tool therefore writes one focused APRX per result map and an adjacent PAGX/PDF/
PNG layout export based on ArcGIS Pro's built-in A4 title-bar template.  Every
APRX contains the actual local raster and mine boundary, not a rendered image.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


LULC_COLORS = {
    1: {"RGB": [34, 94, 168, 100]}, 2: {"RGB": [65, 182, 196, 100]},
    3: {"RGB": [215, 48, 39, 100]}, 4: {"RGB": [253, 174, 97, 100]},
    5: {"RGB": [26, 152, 80, 100]}, 6: {"RGB": [166, 217, 106, 100]},
}
LULC_LABELS = {
    1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地",
}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def prepare_display_raster(raster: Path, kind: str, cache_dir: Path) -> Path:
    """Create a display-only raster with zero background masked.

    InVEST outputs are aligned to the rectangular analysis grid and use 0 as
    the outside-of-study-area value.  ArcGIS stretch rendering treats that 0
    as a real minimum and paints a black rectangle.  The analytical source is
    left untouched; this sidecar only changes zeros to NoData for map export.
    """
    if kind == "lulc":
        return raster
    try:
        from osgeo import gdal
        import numpy as np
        cache_dir.mkdir(parents=True, exist_ok=True)
        out = cache_dir / f"{raster.stem}_display.tif"
        if out.exists():
            return out
        source = gdal.Open(str(raster), gdal.GA_ReadOnly)
        if source is None:
            return raster
        band = source.GetRasterBand(1)
        data = band.ReadAsArray()
        nodata = -9999.0
        data = data.astype("float32", copy=False)
        data[data <= 0] = nodata
        driver = gdal.GetDriverByName("GTiff")
        target = driver.Create(str(out), source.RasterXSize, source.RasterYSize, 1, gdal.GDT_Float32,
                               options=["COMPRESS=LZW", "TILED=YES"])
        target.SetGeoTransform(source.GetGeoTransform())
        target.SetProjection(source.GetProjection())
        out_band = target.GetRasterBand(1)
        out_band.SetNoDataValue(nodata)
        out_band.WriteArray(data)
        out_band.FlushCache(); target.FlushCache(); target = None; source = None
        return out
    except Exception:
        return raster


def text_element(layout: Any, name: str) -> Any | None:
    matches = layout.listElements("TEXT_ELEMENT", name)
    return matches[0] if matches else None


def extent_with_margin(extent: Any, fraction: float = 0.04) -> Any:
    import arcpy
    dx, dy = extent.width * fraction, extent.height * fraction
    return arcpy.Extent(extent.XMin - dx, extent.YMin - dy, extent.XMax + dx, extent.YMax + dy)


def set_lulc_symbology(layer: Any) -> str:
    """Apply discrete colours when this ArcGIS Pro build exposes a raster colorizer."""
    try:
        symbology = layer.symbology
        symbology.updateColorizer("RasterUniqueValueColorizer")
        colorizer = symbology.colorizer
        try:
            # Replace ArcGIS's English field heading in the legend while
            # retaining the raster's unique-value renderer.
            colorizer.field = "土地利用类型"
        except Exception:
            pass
        for group in getattr(colorizer, "groups", []):
            # ArcGIS Pro initially creates one item for the complete byte
            # range (0--255), although the classification raster only has
            # codes 0--6.  Keep only the documented land-use codes so the
            # legend is readable and the NoData/unused classes do not appear.
            valid_items = []
            for item in getattr(group, "items", []):
                raw = getattr(item, "values", [])
                value = None
                if raw:
                    candidate = raw[0]
                    value = candidate[0] if isinstance(candidate, (list, tuple)) and candidate else candidate
                try:
                    code = int(value)
                except (TypeError, ValueError):
                    continue
                if code in LULC_COLORS:
                    item.color = LULC_COLORS[code]
                    item.label = LULC_LABELS[code]
                    valid_items.append(item)
            try:
                group.items = valid_items
            except Exception:
                # Older ArcGIS builds expose items as a read-only proxy.  The
                # labels/colors above still improve the renderer there.
                pass
        layer.symbology = symbology
        return "RasterUniqueValueColorizer"
    except Exception as error:  # A valid APRX is still more useful than a silent abort.
        return f"default_renderer ({error})"


def set_continuous_symbology(aprx: Any, layer: Any, palette: str) -> str:
    try:
        symbology = layer.symbology
        symbology.updateColorizer("RasterStretchColorizer")
        try:
            # Keep masked/NoData cells transparent instead of rendering the
            # rectangular raster footprint as black or white background.
            symbology.colorizer.noDataColor = {"RGB": [255, 255, 255, 0]}
        except Exception:
            pass
        ramps = aprx.listColorRamps(palette)
        if not ramps:
            # The localized ArcGIS Python API occasionally ignores the name
            # filter.  Resolve the same ramp from the complete catalog.
            ramps = [ramp for ramp in aprx.listColorRamps()
                     if str(getattr(ramp, "name", "")).lower() == palette.lower()]
        if ramps:
            symbology.colorizer.colorRamp = ramps[0]
        layer.symbology = symbology
        return f"RasterStretchColorizer:{palette if ramps else 'default'}"
    except Exception as error:
        return f"default_renderer ({error})"


def configure_boundary(layer: Any) -> None:
    try:
        symbology = layer.symbology
        renderer = symbology.renderer
        # Polygon fill must remain transparent; otherwise the boundary layer
        # masks the land-use/service raster in every exported plate.
        renderer.symbol.color = {"RGB": [255, 255, 255, 0]}
        renderer.symbol.outlineColor = {"RGB": [35, 35, 35, 100]}
        renderer.symbol.size = 1.2
        layer.symbology = symbology
    except Exception:
        pass


def configure_context(layer: Any) -> None:
    """Style the six-city boundary as a subdued context layer in the APRX."""
    try:
        symbology = layer.symbology
        renderer = symbology.renderer
        # The six-city frame is a geographic outline, not an opaque mask.
        renderer.symbol.color = {"RGB": [255, 255, 255, 0]}
        renderer.symbol.outlineColor = {"RGB": [104, 112, 121, 100]}
        renderer.symbol.size = 0.55
        layer.symbology = symbology
    except Exception:
        pass


def aligned_boundary(boundary: Path, reference_raster: Path, output: Path) -> Path:
    """Project a supplied mine boundary to the analysis raster CRS without editing it."""
    import arcpy
    source_sr = arcpy.Describe(str(boundary)).spatialReference
    target_sr = arcpy.Describe(str(reference_raster)).spatialReference
    if not target_sr or target_sr.name == "Unknown":
        raise RuntimeError(f"reference raster has no usable CRS: {reference_raster}")
    if source_sr and source_sr.name != "Unknown" and source_sr.exportToString() == target_sr.exportToString():
        return boundary
    output.parent.mkdir(parents=True, exist_ok=True)
    if arcpy.Exists(str(output)):
        arcpy.management.Delete(str(output))
    arcpy.management.Project(str(boundary), str(output), target_sr)
    return output


def export_layout(aprx: Any, map_object: Any, title: str, year_label: str, boundary: Path,
                  raster: Path, kind: str, pagx_template: Path, output_base: Path,
                  context_boundary: Path | None = None) -> list[str]:
    import arcpy
    layout = arcpy.mp.ConvertLayoutFileToLayout(str(pagx_template))
    frame = layout.listElements("MAPFRAME_ELEMENT", "地图框")[0]
    # ConvertLayoutFileToLayout creates a temporary project.  Assigning a map
    # object owned by another APRX leaves the frame with an empty layer
    # collection in ArcGIS Pro 3.0.  Populate the template's own map instead;
    # this is the important detail that makes the exported PDF/PNG render the
    # actual raster rather than a blank map frame.
    layout_map = frame.map
    for existing in list(layout_map.listLayers()):
        layout_map.removeLayer(existing)
    display_raster = prepare_display_raster(raster, kind, output_base.parent.parent / "display_rasters")
    raster_layer = layout_map.addDataFromPath(str(display_raster))
    raster_layer.name = {
        "lulc": "土地利用类型", "carbon": "碳储量", "water_yield": "水源供给",
        "habitat_quality": "生境质量", "ecosystem_service": "综合生态服务",
        "subsidence": "沉陷深度",
    }.get(kind, title)
    # Cividis is available in both English and Chinese ArcGIS installations;
    # using one perceptually ordered ramp keeps the five service plates
    # comparable across machines.
    continuous_ramps = {
        "carbon": "Cividis", "subsidence": "Cividis",
        "water_yield": "Cividis", "habitat_quality": "Cividis",
        "ecosystem_service": "Cividis",
    }
    if kind == "lulc":
        set_lulc_symbology(raster_layer)
    else:
        set_continuous_symbology(aprx, raster_layer, continuous_ramps.get(kind, "Yellow to Blue"))
    boundary_layer = layout_map.addDataFromPath(str(boundary))
    boundary_layer.name = "矿区边界"
    configure_boundary(boundary_layer)
    if context_boundary:
        context_layer = layout_map.addDataFromPath(str(context_boundary))
        context_layer.name = "皖北六市范围（制图底图）"
        configure_context(context_layer)
    frame.map = layout_map
    # Use the complete six-city extent when a context layer is supplied.  This
    # keeps the mining patches in geographic context while retaining a single
    # stable map frame for every year and service.
    view_boundary = context_boundary or boundary
    frame.camera.setExtent(extent_with_margin(arcpy.Describe(str(view_boundary)).extent, fraction=0.012))
    legend = layout.listElements("LEGEND_ELEMENT", "图例")
    if legend:
        legend[0].mapFrame = frame
        # Thesis-style plate: legend at lower left, clear of the analytical
        # patches, rather than the title-bar template's right column.
        legend[0].elementPositionX = 5.0
        legend[0].elementPositionY = 78.0
        legend[0].elementWidth = 53.0
        legend[0].elementHeight = 82.0
        legend[0].showTitle = True
        legend[0].title = "图例"
    for scale in layout.listElements("MAPSURROUND_ELEMENT", "比例尺"):
        # The paper plate places the scale bar away from the lower-left
        # legend, leaving both readable.
        scale.elementPositionX = 226.0
        scale.elementPositionY = 22.7
        # Keep the legend focused on the analytical raster.  Boundary/context
        # outlines are visible for orientation but do not need duplicate
        # legend swatches.  Visible-feature mode prevents empty layers from
        # expanding the legend where the ArcGIS renderer supports it.
        for item in list(legend[0].items):
            if item.name != raster_layer.name:
                try:
                    legend[0].removeItem(item)
                except Exception:
                    item.visible = False
            else:
                try:
                    item.showVisibleFeatures = True
                    item.showFeatureCount = False
                except Exception:
                    pass
    title_element = text_element(layout, "地图标题")
    if title_element:
        title_element.text = title
        # Move the title into the upper margin of the map frame.  The built-in
        # title-bar graphic is hidden below, matching the supplied thesis
        # plate where the map has a clean border and an in-frame title.
        title_element.elementPositionX = 62.0
        title_element.elementPositionY = 202.0
        title_element.elementWidth = 173.0
        title_element.elementHeight = 6.0
        title_element.textSize = 12.0
    author_element = text_element(layout, "服务图层制作者名单")
    if author_element:
        # The paper-style plate should not contain software credits or an
        # English footer.  Keep the element empty rather than deleting the
        # template element, which is safer across ArcGIS Pro versions.
        author_element.text = ""
        author_element.visible = False
    for graphic in layout.listElements("GRAPHIC_ELEMENT", "边界"):
        graphic.visible = False
    ensure_parent(output_base)
    pagx, pdf, png = output_base.with_suffix(".pagx"), output_base.with_suffix(".pdf"), output_base.with_suffix(".png")
    layout.exportToPAGX(str(pagx))
    layout.exportToPDF(str(pdf), resolution=300)
    layout.exportToPNG(str(png), resolution=300)
    return [str(pagx), str(pdf), str(png)]


def create_one(source_aprx: Path, output_aprx: Path, boundary: Path, raster: Path, title: str,
               kind: str, pagx_template: Path, layout_base: Path, context_boundary: Path | None = None) -> dict[str, Any]:
    import arcpy
    ensure_parent(output_aprx)
    if output_aprx.exists():
        output_aprx.unlink()
    shutil.copy2(source_aprx, output_aprx)
    aprx = arcpy.mp.ArcGISProject(str(output_aprx))
    maps = aprx.listMaps()
    if len(maps) != 1:
        raise RuntimeError(f"template project must contain exactly one map: {source_aprx}")
    map_object = maps[0]
    for layer in list(map_object.listLayers()):
        map_object.removeLayer(layer)
    raster_layer = map_object.addDataFromPath(str(raster))
    raster_layer.name = title
    continuous_ramps = {
        "carbon": "Orange to Red",
        "subsidence": "Blue to Green",
        "water_yield": "Yellow to Blue",
        "habitat_quality": "Yellow to Green",
        "ecosystem_service": "Red to Green",
    }
    renderer = set_lulc_symbology(raster_layer) if kind == "lulc" else set_continuous_symbology(
        aprx, raster_layer, continuous_ramps.get(kind, "Yellow to Blue"))
    boundary_layer = map_object.addDataFromPath(str(boundary))
    boundary_layer.name = "矿区边界"
    configure_boundary(boundary_layer)
    if context_boundary:
        context_layer = map_object.addDataFromPath(str(context_boundary))
        context_layer.name = "皖北六市范围（制图底图）"
        configure_context(context_layer)
        try:
            map_object.moveLayer(raster_layer, context_layer, "AFTER")
        except Exception:
            pass
    aprx.save()
    exports = export_layout(aprx, map_object, title, "", boundary, raster, kind, pagx_template,
                            layout_base, context_boundary=context_boundary)
    return {"title": title, "kind": kind, "raster": str(raster), "aprx": str(output_aprx),
            "renderer": renderer, "exports": exports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-aprx", required=True, type=Path)
    parser.add_argument("--layout-template", required=True, type=Path,
                        help="ArcGIS Pro PAGX template selected from this computer's installation")
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--context-boundary", type=Path,
                        help="Optional six-city boundary stored in each APRX as a context layer.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--lulc", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--carbon", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--water-yield", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--habitat-quality", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--ecosystem-service", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--subsidence", type=Path)
    args = parser.parse_args()
    source, boundary, output = (args.source_aprx.resolve(), args.boundary.resolve(), args.output_dir.resolve())
    template = args.layout_template.expanduser().resolve()
    if not source.is_file() or not boundary.is_file() or not template.is_file():
        raise SystemExit("source APRX, mine boundary, or local A4 layout template is unavailable")
    source_records = [raw.partition("=")[2] for raw in [*args.lulc, *args.carbon, *args.water_yield,
                                                           *args.habitat_quality, *args.ecosystem_service] if "=" in raw]
    if args.subsidence:
        source_records.append(str(args.subsidence))
    if not source_records:
        raise SystemExit("at least one LULC, Carbon, or subsidence raster is required")
    aligned = aligned_boundary(boundary, Path(source_records[0]).resolve(), output / "inputs" / "mine_boundary_analysis_crs.shp")
    context_aligned = None
    if args.context_boundary:
        context_aligned = aligned_boundary(args.context_boundary.resolve(), Path(source_records[0]).resolve(),
                                           output / "inputs" / "wanbei_six_cities_analysis_crs.shp")
    records: list[dict[str, Any]] = []
    for raw in args.lulc:
        year, sep, value = raw.partition("=")
        raster = Path(value).resolve()
        if not sep or not raster.is_file():
            raise SystemExit(f"invalid --lulc input: {raw}")
        records.append(create_one(source, output / "aprx" / f"土地利用_{year}.aprx", aligned, raster,
                                  f"{year}年土地利用分类图", "lulc", template, output / "layouts" / f"土地利用_{year}", context_aligned))
    for raw in args.carbon:
        year, sep, value = raw.partition("=")
        raster = Path(value).resolve()
        if not sep or not raster.is_file():
            raise SystemExit(f"invalid --carbon input: {raw}")
        records.append(create_one(source, output / "aprx" / f"碳储量_{year}.aprx", aligned, raster,
                                  f"{year}年碳储量空间分布（Mg C / 像元）", "carbon", template,
                                  output / "layouts" / f"碳储量_{year}", context_aligned))
    for raw in args.water_yield:
        year, sep, value = raw.partition("=")
        raster = Path(value).resolve()
        if not sep or not raster.is_file():
            raise SystemExit(f"invalid --water-yield input: {raw}")
        records.append(create_one(source, output / "aprx" / f"水源供给_{year}.aprx", aligned, raster,
                                  f"{year}年水源供给", "water_yield", template,
                                  output / "layouts" / f"水源供给_{year}", context_aligned))
    for raw in args.habitat_quality:
        year, sep, value = raw.partition("=")
        raster = Path(value).resolve()
        if not sep or not raster.is_file():
            raise SystemExit(f"invalid --habitat-quality input: {raw}")
        records.append(create_one(source, output / "aprx" / f"生境质量_{year}.aprx", aligned, raster,
                                  f"{year}年生境质量", "habitat_quality", template,
                                  output / "layouts" / f"生境质量_{year}", context_aligned))
    for raw in args.ecosystem_service:
        year, sep, value = raw.partition("=")
        raster = Path(value).resolve()
        if not sep or not raster.is_file():
            raise SystemExit(f"invalid --ecosystem-service input: {raw}")
        records.append(create_one(source, output / "aprx" / f"综合生态服务_{year}.aprx", aligned, raster,
                                  f"{year}年综合生态服务指数", "ecosystem_service", template,
                                  output / "layouts" / f"综合生态服务_{year}", context_aligned))
    if args.subsidence:
        raster = args.subsidence.resolve()
        if not raster.is_file():
            raise SystemExit(f"missing subsidence raster: {raster}")
        records.append(create_one(source, output / "aprx" / "沉陷云图_2025.aprx", aligned, raster,
                                  "2025年预测地表沉陷深度（m，正值向下）", "subsidence", template,
                                  output / "layouts" / "沉陷云图_2025", context_aligned))
    manifest = {"status": "completed", "layout_template": str(template), "source_boundary": str(boundary),
                "analysis_crs_boundary": str(aligned), "context_boundary": str(context_aligned) if context_aligned else None, "products": records,
                "note": "Each APRX contains source raster and mine boundary. Layout exports are sidecar PAGX/PDF/PNG files."}
    output.mkdir(parents=True, exist_ok=True)
    (output / "map_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
