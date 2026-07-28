#!/usr/bin/env python3
"""Sensor-aware, inspectable defaults for local LULC classification.

The profiles in this module are *starting points*, rather than hidden model
parameters.  They keep the spectral-band ordering and spatial-resolution
choices explicit before an ENVI or PyTorch classifier is run.  A model package
still owns its own preprocessing contract and takes precedence over these
recommendations when the two differ.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_ALIASES = {
    "landsat_5": "landsat_5_tm",
    "landsat5": "landsat_5_tm",
    "landsat 5": "landsat_5_tm",
    "landsat_5_tm": "landsat_5_tm",
    "landsat 5 tm": "landsat_5_tm",
    "landsat_8": "landsat_8_oli",
    "landsat8": "landsat_8_oli",
    "landsat 8": "landsat_8_oli",
    "landsat_8_oli": "landsat_8_oli",
    "landsat 8 oli": "landsat_8_oli",
    "sentinel_2": "sentinel_2_msi",
    "sentinel2": "sentinel_2_msi",
    "sentinel-2": "sentinel_2_msi",
    "sentinel 2": "sentinel_2_msi",
    "sentinel_2_msi": "sentinel_2_msi",
    "sentinel-2 msi": "sentinel_2_msi",
}


_PROFILES: dict[str, dict[str, Any]] = {
    "landsat_5_tm": {
        "sensor": "Landsat 5 TM",
        "sensor_id": "landsat_5_tm",
        "recommended_product": "Landsat Collection 2 Level-2 surface reflectance",
        "native_resolution_m": 30,
        "classification_resolution_m": 30,
        "analysis_grid_resolution_m": 30,
        "canonical_band_order": ["blue", "green", "red", "nir", "swir1", "swir2"],
        "source_bands": ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"],
        "feature_stack": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndwi", "mndwi", "ndbi"],
        "cloud_mask": {"qa_band": "QA_PIXEL", "remove": ["fill", "dilated_cloud", "cloud", "cloud_shadow", "snow"]},
        "continuous_resampling": "bilinear",
        "classified_resampling": "nearest",
        "post_classification_to_analysis_grid": "not_required",
        "notes": [
            "Use the six reflective bands in the stated order; do not substitute the thermal band for SWIR2.",
            "Apply the Collection-2 scale/offset only when the input is stored as scaled integer reflectance.",
        ],
    },
    "landsat_8_oli": {
        "sensor": "Landsat 8 OLI",
        "sensor_id": "landsat_8_oli",
        "recommended_product": "Landsat Collection 2 Level-2 surface reflectance",
        "native_resolution_m": 30,
        "classification_resolution_m": 30,
        "analysis_grid_resolution_m": 30,
        "canonical_band_order": ["blue", "green", "red", "nir", "swir1", "swir2"],
        "source_bands": ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"],
        "feature_stack": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndwi", "mndwi", "ndbi"],
        "cloud_mask": {"qa_band": "QA_PIXEL", "remove": ["fill", "dilated_cloud", "cloud", "cloud_shadow", "snow"]},
        "continuous_resampling": "bilinear",
        "classified_resampling": "nearest",
        "post_classification_to_analysis_grid": "not_required",
        "notes": [
            "Do not mix the coastal aerosol (B1), panchromatic (B8), cirrus (B9), or thermal bands into this six-band optical profile.",
            "A Landsat 8 model cannot silently reuse Landsat 5 band statistics; validate cross-sensor transfer independently.",
        ],
    },
    "sentinel_2_msi": {
        "sensor": "Sentinel-2 MSI",
        "sensor_id": "sentinel_2_msi",
        "recommended_product": "Sentinel-2 Level-2A surface reflectance",
        "native_resolution_m": 10,
        "classification_resolution_m": 10,
        "analysis_grid_resolution_m": 30,
        "canonical_band_order": ["blue", "green", "red", "nir", "swir1", "swir2"],
        "source_bands": ["B2", "B3", "B4", "B8", "B11", "B12"],
        "feature_stack": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndwi", "mndwi", "ndbi"],
        "cloud_mask": {"qa_band": "SCL", "remove": ["no_data", "saturated", "cloud_shadow", "cloud_medium", "cloud_high", "cirrus", "snow"]},
        "continuous_resampling": "bilinear",
        "classified_resampling": "nearest",
        "post_classification_to_analysis_grid": "majority_10m_to_30m",
        "notes": [
            "B11 and B12 are 20 m; resample reflectance to the 10 m classification grid before calculating SWIR-based indices.",
            "For the fixed 30 m analysis grid, aggregate the completed categorical LULC map by majority value; do not bilinearly average class codes.",
        ],
    },
}


_METHODS: dict[str, dict[str, Any]] = {
    "maximum_likelihood": {
        "method": "maximum_likelihood",
        "engine": "envi",
        "minimum_sample_guidance": "At least 10 independent training units per input feature, with substantially more for stable covariance estimates.",
        "normalization": "Use consistently scaled reflectance and inspect class covariance/overlap before fitting.",
        "use_when": "Class distributions are reasonably compact and sample support is adequate.",
    },
    "minimum_distance": {
        "method": "minimum_distance",
        "engine": "envi",
        "minimum_sample_guidance": "Use as a transparent baseline when covariance estimates are weak; it does not replace independent accuracy assessment.",
        "normalization": "Standardize feature scales when features have materially different numeric ranges.",
        "use_when": "Rapid baseline or limited training samples; compare against a held-out validation set.",
    },
}


def _normalize(sensor: str) -> str:
    if not isinstance(sensor, str) or not sensor.strip():
        raise ValueError("sensor must be a non-empty string")
    key = " ".join(sensor.strip().lower().replace("_", " ").split())
    canonical = _ALIASES.get(key) or _ALIASES.get(key.replace(" ", "_"))
    if canonical is None:
        supported = ", ".join(sorted({profile["sensor"] for profile in _PROFILES.values()}))
        raise ValueError(f"unsupported sensor {sensor!r}; supported sensors: {supported}")
    return canonical


def profile(sensor: str, method: str = "auto", scheme: str = "high_water_coal_7class") -> dict[str, Any]:
    """Return a serialisable profile without mutating the published defaults."""
    canonical = _normalize(sensor)
    if method == "auto":
        method = "maximum_likelihood"
    if method not in _METHODS:
        raise ValueError("method must be auto, maximum_likelihood, or minimum_distance")
    if scheme not in {"standard_6class", "high_water_coal_7class"}:
        raise ValueError("scheme must be standard_6class or high_water_coal_7class")
    result = deepcopy(_PROFILES[canonical])
    result["classification_method"] = deepcopy(_METHODS[method])
    result["scheme"] = scheme
    result["class_codes"] = ([1, 2, 3, 4, 5, 6] if scheme == "standard_6class" else [1, 2, 3, 4, 5, 6, 7])
    result["status"] = "completed"
    return result


def supported_sensors() -> list[dict[str, str]]:
    return [{"sensor_id": key, "sensor": value["sensor"]} for key, value in sorted(_PROFILES.items())]
