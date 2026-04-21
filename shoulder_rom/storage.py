from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .camera_panel import camera_settings_from_dict, camera_settings_to_dict, create_default_camera_settings
from .config import TrackbarDefaults
from .models import CameraSettings
from .models import MeasurementRecord, PathCaptureRecord


def load_homography(path: Path) -> Tuple[Optional[np.ndarray], str]:
    if not path.exists():
        return None, "Calibration file {0} was not found. Press C to run calibration.".format(path.name)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        matrix = np.array(data["homography"], dtype=np.float32)
        if matrix.shape != (3, 3):
            return None, "Calibration file format is invalid. Please recalibrate."
        return matrix, "Calibration file {0} loaded.".format(path.name)
    except (OSError, ValueError, KeyError, TypeError):
        return None, "Unable to read the calibration file. Please recalibrate."


def save_homography(path: Path, matrix: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"homography": matrix.tolist()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_measurement_record(path: Path, record: MeasurementRecord, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding=encoding) as csv_file:
        writer = csv.writer(csv_file)
        if needs_header:
            writer.writerow(MeasurementRecord.csv_headers())
        writer.writerow(record.csv_row())


def save_path_capture(directory: Path, record: PathCaptureRecord) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = "path_capture_{0}.json".format(record.timestamp.strftime("%Y%m%d_%H%M%S_%f"))
    path = directory / filename
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_camera_settings(path: Path, defaults: TrackbarDefaults) -> Tuple[CameraSettings, str]:
    if not path.exists():
        return create_default_camera_settings(defaults), "Using default camera settings."

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = camera_settings_from_dict(data, defaults)
        return settings, "Loaded saved camera settings."
    except (OSError, ValueError, TypeError):
        return create_default_camera_settings(defaults), "Camera settings file is invalid. Using defaults."


def save_camera_settings(path: Path, settings: CameraSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(camera_settings_to_dict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
