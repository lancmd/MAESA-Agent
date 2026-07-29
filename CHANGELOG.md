# Changelog

This record tracks user-visible changes to MAESA-Agent. Dates refer to source releases, not to individual research runs.

## 0.3.4 - 2026-07-29

- Finished the remaining Windows Copilot smoke assertion by checking the model-package location relative to the project input directory instead of comparing a temporary absolute path.

## 0.3.3 - 2026-07-29

- Finished the Windows CI path-stability cleanup by checking Copilot validation evidence and output-report paths by their project-relative suffixes.

## 0.3.2 - 2026-07-29

- Completed the Windows CI repair by making the Copilot nested-input smoke assertion independent of the runner's temporary absolute path.

## 0.3.1 - 2026-07-29

- Fixed clean Windows CI runs: smoke tests now create their ignored `outputs/` scratch directory instead of assuming it exists.
- Made the Copilot nested-input assertion compare normalized local paths, avoiding Windows drive-letter and path-casing differences.

## 0.3.0 - 2026-07-27

- Added the `classification_invest` task type for multi-period LULC classification followed by Carbon and Habitat Quality evaluation, without requiring PLUS.
- A project can now give each imagery period its own training ROI and independent validation samples. ROI quality checks and per-period accuracy reports are compiled before the classifier runs.
- Habitat Quality datastacks can be built from a dated LULC raster, threat rasters, and a sensitivity table. Carbon density coverage is checked against the actual LULC codes before InVEST starts.
- Added sensor-aware classification profiles for Landsat 5 TM, Landsat 8 OLI, and Sentinel-2 MSI; six-period InVEST outputs are summarised into a CSV and portable SVG trend figure.
- The local Copilot can turn a natural-language request plus an approved local input inventory into a schema-checked project plan. It remains confirmation-gated and local-tool-only.
- Added an anonymous synthetic six-period example and an opt-in real-data acceptance-test entry point. The example proves contracts and workflow compilation; it is not presented as a real mining-area result.

## 0.2.1 — 2026-07-24

- The `full_chain` project builder now accepts independent LULC validation, ecosystem-service, subsidence-water and ArcGIS layout configurations through the local MCP interface.
- Missing independent samples, ecosystem configuration, or a GIS layout are surfaced as `pending_validation` items rather than silently disabling those modules.
- The distributable MCP wheel now carries its required runtime scripts, interfaces, templates and registered-model metadata; CI verifies the wheel can resolve those assets after installation.

## 0.2.0 — 2026-07-24

- Project construction now runs the full local-project validator and returns its report with the build response.
- `pending_validation` from an analysis command now pauses the workflow and survives to the final job state.
- The shipped PyTorch configuration follows the runtime input contract; the registered ResNet-50 package is pinned to its reviewed SHA-256 fingerprint.
- InVEST-only projects can select Annual Water Yield, Habitat Quality, or other supported models without silently enabling Carbon.
- ArcGIS layout composition recognises common Chinese element names, and discrete class-code checks compare whole values.
- Copilot plans include nested input paths and configured validation evidence/report paths.
- Added portable contract tests and an opt-in local real ResNet-50 inference test.

## 0.1.0 — 2026-07-20

- Initial local-first MCP workflow for classification, PLUS, InVEST, ecosystem service evaluation, and ArcGIS Pro output.
