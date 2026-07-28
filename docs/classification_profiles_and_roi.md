# Classification profiles and ROI quality / 分类参数与 ROI 质检

Use the sensor profile before processing imagery.  It makes the band order,
feature stack, cloud mask, classifier baseline, and target grid explicit.  It
does not override a trained model's documented preprocessing.

```text
get_classification_parameters(sensor="Landsat 5")
get_classification_parameters(sensor="Landsat 8", method="minimum_distance")
get_classification_parameters(sensor="Sentinel-2")
```

The Sentinel-2 profile classifies on a 10 m grid and specifies categorical
majority aggregation to the 30 m analysis grid.  Landsat 5 TM uses
`SR_B1, SR_B2, SR_B3, SR_B4, SR_B5, SR_B7`; Landsat 8 OLI uses
`SR_B2, SR_B3, SR_B4, SR_B5, SR_B6, SR_B7`.

## Executable per-period profile / 逐期可执行参数

For `classification.engine: "envi"`, each item in
`inputs.imagery_periods` needs a `sensor`, unless the project has one shared
`classification.sensor`.  A dated `envi_method` may override the project-wide
method.  The accepted sensors are Landsat 5 TM, Landsat 8 OLI and Sentinel-2
MSI (aliases are normalised); accepted methods are `maximum_likelihood` and
`minimum_distance`.

```json
{
  "year": 2020,
  "path": "data/imagery_2020.tif",
  "sensor": "sentinel_2_msi",
  "envi_method": "maximum_likelihood",
  "training_roi": "data/roi_2020.gpkg"
}
```

During compilation MAESA writes the canonical profile to
`workspace/generated/classification_profiles/` and adds that file as an input
to the ENVI stage through `MINING_CLASSIFICATION_PROFILE`.  The runner checks
that the profile artifact still matches the compiled stage before IDL starts,
so a sensor label cannot silently drift away from the bands, feature stack and
30 m aggregation policy recorded in provenance.

Before classification, run the local ROI check:

```text
check_roi_sample_quality(
  roi_file="C:\\project\\roi2020.xml",
  output="C:\\project\\outputs\\roi_quality_2020.json",
  class_field="class_id",
  expected_classes=["water", "built_up", "cropland", "forest", "grassland", "bare_mining_land"]
)
```

GeoJSON and CSV ROI inputs work without optional GIS libraries.  GeoPackage
and Shapefile inputs use Fiona when installed, or ArcGIS Pro Python as a local
fallback.  ENVI XML inputs such as `roi2020.xml` are supported: every
`Region/GeometryDef/Polygon` is counted, and the Region `name` is exposed as
both `class_id` and `name`.

ENVI XML lacks an inherent training/validation split.  The check reports
`validation_status: pending_validation` until an independent validation layer
or sample table is supplied.  This is intentional; ROI polygon counts are not
treated as independent validation pixels.

For a `classification_invest` run, keep the ENVI ROI training-only and provide
a separate per-period validation CSV with `reference`, `x`, `y`, and an
explicit CRS.  MAESA samples the generated LULC raster at those coordinates;
it does not use a prefilled `prediction` column from the CSV.  When a ROI has
a role field, the workflow rejects any `validation` (or other non-training)
role before ENVI starts, so validation samples cannot leak into model fitting.
