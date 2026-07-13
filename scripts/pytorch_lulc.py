#!/usr/bin/env python3
"""Validate and run portable PyTorch land-use segmentation model packages."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


SUPPORTED_FORMATS = {"exported_program", "torchscript"}


def load_config(package: Path) -> dict[str, Any]:
    path = package / "model_config.json"
    if not path.exists():
        raise FileNotFoundError(f"missing model_config.json: {package}")
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(package: Path, verify_weights: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_config(package)
    except Exception as error:
        return {"status": "invalid", "errors": [str(error)], "warnings": []}
    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not config.get("model_id"):
        errors.append("model_id is required")
    if config.get("format") not in SUPPORTED_FORMATS:
        errors.append(f"format must be one of {sorted(SUPPORTED_FORMATS)}")
    weights = package / str(config.get("weights", ""))
    if not config.get("weights") or not weights.is_file():
        errors.append(f"model weights do not exist: {weights}")
    classes = config.get("classes")
    if not isinstance(classes, list) or len(classes) < 2:
        errors.append("classes must contain at least two entries")
        classes = []
    ids = [item.get("id") for item in classes if isinstance(item, dict)]
    names = [item.get("name") for item in classes if isinstance(item, dict)]
    if len(ids) != len(classes) or any(not isinstance(item, int) or item <= 0 for item in ids):
        errors.append("each class id must be a positive integer")
    if len(set(ids)) != len(ids) or len(set(names)) != len(names) or any(not item for item in names):
        errors.append("class ids and names must be unique and non-empty")
    input_config = config.get("input", {})
    bands = input_config.get("bands", [])
    indexes = input_config.get("band_indexes", [])
    mean = input_config.get("mean", [])
    std = input_config.get("std", [])
    if not bands or not (len(bands) == len(indexes) == len(mean) == len(std)):
        errors.append("bands, band_indexes, mean, and std must have equal non-zero lengths")
    if any(not isinstance(item, int) or item < 1 for item in indexes):
        errors.append("band_indexes must be positive 1-based integers")
    if any(not isinstance(item, (int, float)) or item <= 0 for item in std):
        errors.append("all std values must be positive numbers")
    for field in ("sensor", "resolution_m", "value_range", "scale"):
        if field not in input_config:
            warnings.append(f"input.{field} is not declared; sensor compatibility cannot be fully assessed")
    if input_config.get("resolution_m") is not None and (not isinstance(input_config["resolution_m"], (int, float)) or input_config["resolution_m"] <= 0):
        errors.append("input.resolution_m must be a positive number when supplied")
    value_range = input_config.get("value_range")
    if value_range is not None and (not isinstance(value_range, list) or len(value_range) != 2 or
                                    not all(isinstance(item, (int, float)) for item in value_range) or value_range[0] >= value_range[1]):
        errors.append("input.value_range must be [minimum, maximum] when supplied")
    patch_size = input_config.get("patch_size")
    stride = input_config.get("stride")
    if not isinstance(patch_size, int) or patch_size < 16:
        errors.append("patch_size must be an integer >= 16")
    if not isinstance(stride, int) or not isinstance(patch_size, int) or not 1 <= stride <= patch_size:
        errors.append("stride must be between 1 and patch_size")
    output_config = config.get("output", {})
    if output_config.get("type") not in {"logits", "probabilities"}:
        errors.append("output.type must be logits or probabilities")
    expected_hash = str(config.get("sha256", "")).lower()
    actual_hash = None
    if verify_weights and weights.is_file():
        actual_hash = file_sha256(weights)
        if not expected_hash or expected_hash.startswith("replace_"):
            warnings.append("sha256 is missing; pin the weights hash before production use")
        elif actual_hash != expected_hash:
            errors.append("weights sha256 does not match model_config.json")
    training = config.get("training", {})
    if not training.get("regions") or not training.get("imagery_years"):
        warnings.append("training regions/years are incomplete; transferability cannot be assessed")
    return {
        "status": "valid" if not errors else "invalid",
        "model_id": config.get("model_id"),
        "format": config.get("format"),
        "weights": str(weights),
        "actual_sha256": actual_hash,
        "class_count": len(classes),
        "bands": bands,
        "errors": errors,
        "warnings": warnings,
    }


def _starts(length: int, patch: int, stride: int) -> list[int]:
    if length <= patch:
        return [0]
    values = list(range(0, length - patch + 1, stride))
    final = length - patch
    if values[-1] != final:
        values.append(final)
    return values


def infer(package: Path, input_raster: Path, class_output: Path, confidence_output: Path,
          device_name: str = "auto", low_confidence_output: Path | None = None,
          low_confidence_threshold: float | None = None) -> dict[str, Any]:
    validation = validate_package(package)
    if validation["status"] != "valid":
        raise ValueError("invalid model package: " + "; ".join(validation["errors"]))
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import Window
        import torch
        import torch.nn.functional as functional
    except ImportError as error:
        raise RuntimeError("PyTorch inference requires torch, numpy, and rasterio") from error
    config = load_config(package)
    input_config = config["input"]
    output_config = config["output"]
    device = "cuda" if device_name == "auto" and torch.cuda.is_available() else ("cpu" if device_name == "auto" else device_name)
    weights = package / config["weights"]
    cache = Path(tempfile.mkdtemp(prefix="pytorch_lulc_"))
    staged_weights = cache / ("model" + weights.suffix)
    shutil.copy2(weights, staged_weights)
    try:
        if config["format"] == "exported_program":
            model = torch.export.load(str(staged_weights)).module()
        else:
            model = torch.jit.load(str(staged_weights), map_location=device)
    except Exception:
        shutil.rmtree(cache, ignore_errors=True)
        raise
    model = model.to(device)
    if config["format"] == "torchscript":
        model.eval()
    class_ids = np.asarray([item["id"] for item in config["classes"]])
    class_dtype = "uint8" if int(class_ids.max()) <= 255 else "uint16"
    patch = int(input_config["patch_size"])
    stride = int(input_config["stride"])
    indexes = list(input_config["band_indexes"])
    mean = np.asarray(input_config["mean"], dtype="float32")[:, None, None]
    std = np.asarray(input_config["std"], dtype="float32")[:, None, None]
    scale = float(input_config.get("scale", 1.0))
    offset = float(input_config.get("offset", 0.0))
    threshold = low_confidence_threshold if low_confidence_threshold is not None else output_config.get("low_confidence_threshold")
    if threshold is not None and (not isinstance(threshold, (int, float)) or not 0 < float(threshold) < 1):
        raise ValueError("low_confidence_threshold must be between 0 and 1")
    class_output.parent.mkdir(parents=True, exist_ok=True)
    confidence_output.parent.mkdir(parents=True, exist_ok=True)
    if low_confidence_output:
        low_confidence_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with rasterio.open(input_raster) as source:
            if max(indexes) > source.count:
                raise ValueError(f"input raster has {source.count} bands but model requests {max(indexes)}")
            required_resolution = input_config.get("resolution_m")
            if required_resolution is not None:
                actual_resolution = (abs(float(source.transform.a)) + abs(float(source.transform.e))) / 2
                if abs(actual_resolution - float(required_resolution)) > max(1e-6, float(required_resolution) * 0.01):
                    raise ValueError(f"input resolution {actual_resolution:g} differs from model contract {float(required_resolution):g} m")
            height, width = source.height, source.width
            probability_sum = np.memmap(cache / "probabilities.dat", mode="w+", dtype="float32",
                                        shape=(len(class_ids), height, width))
            weight_sum = np.memmap(cache / "weights.dat", mode="w+", dtype="float32", shape=(height, width))
            probability_sum[:] = 0
            weight_sum[:] = 0
            blend_1d = np.hanning(patch).astype("float32")
            if not blend_1d.any():
                blend_1d[:] = 1
            blend = np.maximum(np.outer(blend_1d, blend_1d), 0.05)
            with torch.inference_mode():
                for row in _starts(height, patch, stride):
                    for col in _starts(width, patch, stride):
                        valid_height = min(patch, height - row)
                        valid_width = min(patch, width - col)
                        window = Window(col, row, patch, patch)
                        data = source.read(indexes, window=window, boundless=True, fill_value=0).astype("float32")
                        valid = source.dataset_mask(window=window, boundless=True) > 0
                        data = ((data * scale + offset) - mean) / std
                        tensor = torch.from_numpy(data[None]).to(device)
                        prediction = model(tensor)
                        if isinstance(prediction, dict):
                            prediction = prediction[output_config.get("tensor_key") or next(iter(prediction))]
                        elif isinstance(prediction, (tuple, list)):
                            prediction = prediction[int(output_config.get("tensor_index", 0))]
                        if prediction.ndim != 4 or prediction.shape[0] != 1 or prediction.shape[1] != len(class_ids):
                            raise ValueError(f"model output must be [1,{len(class_ids)},H,W], got {tuple(prediction.shape)}")
                        if tuple(prediction.shape[-2:]) != (patch, patch):
                            prediction = functional.interpolate(prediction, size=(patch, patch), mode="bilinear", align_corners=False)
                        probabilities = (torch.softmax(prediction, dim=1) if output_config["type"] == "logits" else prediction.clamp_min(0))
                        if output_config["type"] == "probabilities":
                            probabilities = probabilities / probabilities.sum(dim=1, keepdim=True).clamp_min(1e-12)
                        probabilities = probabilities[0].detach().float().cpu().numpy()
                        weight = blend[:valid_height, :valid_width] * valid[:valid_height, :valid_width]
                        probability_sum[:, row:row + valid_height, col:col + valid_width] += probabilities[:, :valid_height, :valid_width] * weight
                        weight_sum[row:row + valid_height, col:col + valid_width] += weight
            class_profile = source.profile.copy()
            class_profile.update(count=1, dtype=class_dtype, nodata=output_config.get("class_nodata", 0), compress="deflate")
            confidence_profile = source.profile.copy()
            confidence_profile.update(count=1, dtype="float32", nodata=output_config.get("confidence_nodata", -9999.0), compress="deflate")
            low_profile = source.profile.copy()
            low_profile.update(count=1, dtype="uint8", nodata=255, compress="deflate")
            with ExitStack() as stack:
                class_sink = stack.enter_context(rasterio.open(class_output, "w", **class_profile))
                confidence_sink = stack.enter_context(rasterio.open(confidence_output, "w", **confidence_profile))
                low_sink = stack.enter_context(rasterio.open(low_confidence_output, "w", **low_profile)) if low_confidence_output else None
                for _, window in class_sink.block_windows(1):
                    row = int(window.row_off); col = int(window.col_off)
                    h = int(window.height); w = int(window.width)
                    weights = weight_sum[row:row + h, col:col + w]
                    valid = weights > 0
                    probabilities = probability_sum[:, row:row + h, col:col + w] / np.maximum(weights[None], 1e-12)
                    labels = np.full((h, w), output_config.get("class_nodata", 0), dtype=class_dtype)
                    confidence = np.full((h, w), output_config.get("confidence_nodata", -9999.0), dtype="float32")
                    labels[valid] = class_ids[np.argmax(probabilities[:, valid], axis=0)]
                    confidence[valid] = np.max(probabilities[:, valid], axis=0)
                    class_sink.write(labels, 1, window=window)
                    confidence_sink.write(confidence, 1, window=window)
                    if low_sink:
                        low = np.full((h, w), 255, dtype="uint8")
                        low[valid] = (confidence[valid] < float(threshold)).astype("uint8") if threshold is not None else 0
                        low_sink.write(low, 1, window=window)
        report = {"status": "completed", "model_id": config["model_id"], "device": device,
                  "input_raster": str(input_raster.resolve()), "class_output": str(class_output.resolve()),
                  "confidence_output": str(confidence_output.resolve()), "low_confidence_output": str(low_confidence_output.resolve()) if low_confidence_output else None,
                  "low_confidence_threshold": threshold, "validation_status": "pending_validation"}
        class_output.with_suffix(class_output.suffix + ".inference.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-model")
    validate.add_argument("--model-package", required=True, type=Path)
    validate.add_argument("--skip-weights-hash", action="store_true")
    run = commands.add_parser("infer")
    run.add_argument("--model-package", required=True, type=Path)
    run.add_argument("--input-raster", required=True, type=Path)
    run.add_argument("--class-output", required=True, type=Path)
    run.add_argument("--confidence-output", required=True, type=Path)
    run.add_argument("--low-confidence-output", type=Path)
    run.add_argument("--low-confidence-threshold", type=float)
    run.add_argument("--device", default="auto")
    args = parser.parse_args()
    if args.command == "validate-model":
        result = validate_package(args.model_package.resolve(), not args.skip_weights_hash)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "valid" else 1
    result = infer(args.model_package.resolve(), args.input_raster.resolve(), args.class_output.resolve(),
                   args.confidence_output.resolve(), args.device,
                   args.low_confidence_output.resolve() if args.low_confidence_output else None, args.low_confidence_threshold)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
