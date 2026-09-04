# Changelog

This record tracks user-visible changes to MAESA Skill. Dates refer to source releases, not to individual research runs.

## 0.6.0 - 2026-09-04

- Repositioned the project as MAESA Skill, renamed the public Skill to `mining-area-ecological-analysis`, and renamed setup, startup, verification and workflow-runner entry points accordingly.
- Removed the real-study demonstration, case report builders and region-specific preparation/rendering code from the distributable repository. The remaining synthetic regression data are generated and contain no real study-area observations.
- Generalised study-area labels and output names used by population, ArcGIS, subsidence and mine-carbon utilities so projects from any mining region can supply their own boundary and title.
- Renamed the persistent execution record to `workflow_state.json`; readers retain a legacy fallback for existing local projects.
- Restored Python 3.11 compatibility by removing the case-specific report module that used Python 3.12-only nested f-string syntax.

## 0.5.0 - 2026-09-03

- Added a strict six-class mining-area contract that keeps subsidence water and natural water separate across harmonization, transition statistics, Carbon, Annual Water Yield, Habitat Quality and scenario reporting.
- Materialised the PLUS LEAS land-expansion raster and aligned driver stack before GUI execution. RE now derives and validates its separate 0/1 UInt8 development-zone mask from aligned subsidence depth. CARS validates non-empty class-potential layers, adopts completed vendor outputs without relaunching the GUI, records realised class demand and preserves independent ND/UD/EP/RE state.
- Added native InVEST 3.18 scenario datastacks, common-validity support statistics and publication/report utilities using explicit units and provenance.
- Replaced dated result-organising and deletion helpers with a plan-driven finalizer. It previews by default, constrains every path to the project root, protects declared raw-input roots and writes a final artifact manifest.
- Expanded the Skill routing and documentation for safe final packaging, and removed one-off report patchers and generated repository artifacts.

## 0.4.2 - 2026-07-30

- Added `project_readiness.py` and the local MCP `inspect_local_project_readiness` tool. They compile a project without opening commercial GIS software, inspect real spatial inputs, check dated ROI and independent validation tables, inventory input hashes, list planned stages and identify unavailable local software.
- Documented the readiness report in the install/run path and made `maesa_doctor.ps1` point users to it before analysis.
- Added a real tiny-raster readiness regression and wheel-asset assertion so the pre-run inspection remains available in the standalone MCP package.

## 0.4.1 - 2026-07-29

- Split the README into Skill installation and local development/run paths. Added `maesa_doctor.ps1` for one local dependency, software, GPU and project-data diagnostic, plus an occupied-port guard before MCP starts.
- Added a copyable six-period real-project template. Its data folders are empty by design and its project file is clearly marked as an example.
- Added a classifier input preflight stage. It checks supervised ROI field/category/geometry/CRS conditions and reports per-class independent validation sample counts before ENVI or configured PyTorch accuracy evaluation starts.
- Added an InVEST parameter report stage for every dated and scenario datastack. Carbon reports density codes and pools in Mg C/ha; Habitat Quality reports its half-saturation constant and threat parameters.

## 0.4.0 - 2026-07-29

- Replaced the scattered ArcGIS, ENVI, PLUS, InVEST, data-source and Copilot guides with seven task-centred documents under `docs/`.
- Simplified the README and Skill entry point; runtime bridges, schemas, templates, examples and regression tests remain unchanged.

## 0.3.5 - 2026-07-29

- Serialised local job-record replacement and added bounded retries for Windows file handles, preventing the job launcher and its worker from racing on the same registry record.

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
