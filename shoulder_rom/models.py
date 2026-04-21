from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


Point = Tuple[int, int]
Rect = Tuple[int, int, int, int]


class MeasurementPhase(Enum):
    IDLE = auto()
    START_MARKED = auto()
    COMPLETE = auto()


class AppMode(Enum):
    IDLE = auto()
    MEASUREMENT = auto()
    PRACTICE = auto()


@dataclass
class TrackbarValues:
    exposure: int
    focus: int
    min_brightness: int
    min_area: int
    ignore_bottom: int


@dataclass
class CameraSettings:
    exposure: int
    focus: int
    min_brightness: int
    min_area: int
    ignore_bottom: int
    panel_visible: bool = False

    def to_trackbar_values(self) -> TrackbarValues:
        return TrackbarValues(
            exposure=self.exposure,
            focus=self.focus,
            min_brightness=self.min_brightness,
            min_area=self.min_area,
            ignore_bottom=self.ignore_bottom,
        )


@dataclass
class ControlPanelLayout:
    toolbar_button_rects: Optional[dict[str, Rect]] = None
    decrease_rects: Optional[dict[str, Rect]] = None
    increase_rects: Optional[dict[str, Rect]] = None

    def __post_init__(self) -> None:
        if self.toolbar_button_rects is None:
            self.toolbar_button_rects = {}
        if self.decrease_rects is None:
            self.decrease_rects = {}
        if self.increase_rects is None:
            self.increase_rects = {}


@dataclass
class DetectionResult:
    camera_point: Optional[tuple[float, float]] = None
    screen_point: Optional[Point] = None
    radius: float = 0.0
    area: float = 0.0
    in_screen_bounds: bool = False


@dataclass
class MeasurementMetrics:
    total_cm: float
    one_third_cm: float
    two_third_cm: float


@dataclass
class PathCaptureRecord:
    timestamp: datetime
    raw_points: list[Point]
    filtered_points: list[Point]
    segment_count: int
    scale_cm: float
    scale_pixels: int

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "segment_count": self.segment_count,
            "scale_cm": self.scale_cm,
            "scale_pixels": self.scale_pixels,
            "raw_points": [[x, y] for x, y in self.raw_points],
            "filtered_points": [[x, y] for x, y in self.filtered_points],
        }


@dataclass
class MeasurementRecord:
    timestamp: datetime
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    total_cm: float
    one_third_cm: float
    two_third_cm: float
    scale_cm: float
    scale_pixels: int
    calibration_file: str
    notes: str = ""

    @staticmethod
    def csv_headers() -> list[str]:
        return [
            "date",
            "time",
            "start_x",
            "start_y",
            "end_x",
            "end_y",
            "total_cm",
            "one_third_cm",
            "two_third_cm",
            "scale_cm",
            "scale_pixels",
            "calibration_file",
            "notes",
        ]

    def csv_row(self) -> list[str]:
        return [
            self.timestamp.strftime("%Y-%m-%d"),
            self.timestamp.strftime("%H:%M:%S"),
            str(self.start_x),
            str(self.start_y),
            str(self.end_x),
            str(self.end_y),
            f"{self.total_cm:.2f}",
            f"{self.one_third_cm:.2f}",
            f"{self.two_third_cm:.2f}",
            f"{self.scale_cm:.2f}",
            str(self.scale_pixels),
            self.calibration_file,
            self.notes,
        ]


@dataclass
class AppState:
    mode: AppMode
    homography_matrix: Optional[np.ndarray]
    calibrating: bool
    is_fullscreen: bool
    is_borderless: bool
    phase: MeasurementPhase
    start_point: Optional[Point]
    end_point: Optional[Point]
    scale_cm: float
    segment_count: int
    camera_settings: CameraSettings
    detection: DetectionResult
    raw_path_points: list[Point] = field(default_factory=list)
    filtered_path_points: list[Point] = field(default_factory=list)
    practice_segment_start: int = 1
    practice_segment_end: int = 1
    last_path_file: Optional[Path] = None
    latest_message: str = ""
    csv_path: Optional[Path] = None
    control_panel_layout: Optional[ControlPanelLayout] = None

    @property
    def measurement_ready(self) -> bool:
        return (
            self.phase == MeasurementPhase.COMPLETE
            and self.start_point is not None
            and self.end_point is not None
        )
