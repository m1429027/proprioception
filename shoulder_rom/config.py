from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


CONTROL_WINDOW_NAME = "Control Panel"
PROJECTOR_WINDOW_NAME = "Projector Screen"


@dataclass(frozen=True)
class CameraConfig:
    camera_id: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    disable_autofocus: bool = True


@dataclass(frozen=True)
class ScreenConfig:
    width: int = 1920
    height: int = 1080
    scale_bar_pixels: int = 50


@dataclass(frozen=True)
class CalibrationConfig:
    marker_margin: int = 150
    marker_size: int = 200
    calibration_path: Path = Path("data/calibration/calibration_data_cv.json")


@dataclass(frozen=True)
class SettingsConfig:
    camera_settings_path: Path = Path("data/settings/camera_settings.json")


@dataclass(frozen=True)
class PathConfig:
    capture_directory: Path = Path("data/paths")
    smoothing_window: int = 5
    outlier_multiplier: float = 3.5
    minimum_jump_threshold: float = 12.0


@dataclass(frozen=True)
class ExamConfig:
    output_directory: Path = Path("data/exams")


@dataclass(frozen=True)
class SubjectConfig:
    root_directory: Path = Path("data/subjects")


@dataclass
class TrackbarDefaults:
    exposure: int = 6
    focus: int = 0
    min_brightness: int = 230
    min_area: int = 5
    ignore_bottom: int = 100

    def as_pairs(self) -> list[tuple[str, int, int]]:
        return [
            ("Exposure", self.exposure, 13),
            ("Focus", self.focus, 255),
            ("Min Bright", self.min_brightness, 255),
            ("Min Area", self.min_area, 200),
            ("Ignore Bot", self.ignore_bottom, 300),
        ]


@dataclass(frozen=True)
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    exams: ExamConfig = field(default_factory=ExamConfig)
    subjects: SubjectConfig = field(default_factory=SubjectConfig)
    trackbars: TrackbarDefaults = field(default_factory=TrackbarDefaults)
    default_scale_cm: float = 50.0
    csv_encoding: str = "utf-8-sig"
    supported_platform: str = "Windows"
