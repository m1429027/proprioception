from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import TrackbarDefaults
from .models import CameraSettings


@dataclass(frozen=True)
class CameraSettingSpec:
    key: str
    label: str
    min_value: int
    max_value: int
    step: int = 1


SETTING_SPECS: List[CameraSettingSpec] = [
    CameraSettingSpec("exposure", "Exposure", 0, 13, 1),
    CameraSettingSpec("focus", "Focus", 0, 255, 5),
    CameraSettingSpec("min_brightness", "Min Bright", 0, 255, 5),
    CameraSettingSpec("min_area", "Min Area", 1, 200, 1),
    CameraSettingSpec("ignore_bottom", "Ignore Bot", 0, 300, 5),
]


def create_default_camera_settings(defaults: TrackbarDefaults) -> CameraSettings:
    return CameraSettings(
        exposure=defaults.exposure,
        focus=defaults.focus,
        min_brightness=defaults.min_brightness,
        min_area=defaults.min_area,
        ignore_bottom=defaults.ignore_bottom,
        panel_visible=False,
    )


def clamp_camera_settings(settings: CameraSettings) -> CameraSettings:
    values = {}
    for spec in SETTING_SPECS:
        raw_value = getattr(settings, spec.key)
        values[spec.key] = max(spec.min_value, min(spec.max_value, int(raw_value)))
    values["panel_visible"] = bool(settings.panel_visible)
    return CameraSettings(**values)


def update_setting_value(settings: CameraSettings, key: str, delta: int) -> CameraSettings:
    spec = find_setting_spec(key)
    if spec is None:
        return settings

    current = getattr(settings, key)
    new_value = current + (spec.step * delta)
    clamped = max(spec.min_value, min(spec.max_value, new_value))
    updated = CameraSettings(
        exposure=settings.exposure,
        focus=settings.focus,
        min_brightness=settings.min_brightness,
        min_area=settings.min_area,
        ignore_bottom=settings.ignore_bottom,
        panel_visible=settings.panel_visible,
    )
    setattr(updated, key, clamped)
    return updated


def camera_settings_to_dict(settings: CameraSettings) -> dict:
    return {
        "exposure": settings.exposure,
        "focus": settings.focus,
        "min_brightness": settings.min_brightness,
        "min_area": settings.min_area,
        "ignore_bottom": settings.ignore_bottom,
        "panel_visible": settings.panel_visible,
    }


def camera_settings_from_dict(data: dict, defaults: TrackbarDefaults) -> CameraSettings:
    base = create_default_camera_settings(defaults)
    loaded = CameraSettings(
        exposure=int(data.get("exposure", base.exposure)),
        focus=int(data.get("focus", base.focus)),
        min_brightness=int(data.get("min_brightness", base.min_brightness)),
        min_area=int(data.get("min_area", base.min_area)),
        ignore_bottom=int(data.get("ignore_bottom", base.ignore_bottom)),
        panel_visible=bool(data.get("panel_visible", False)),
    )
    # Keep panel hidden on startup even if the last state was visible.
    loaded.panel_visible = False
    return clamp_camera_settings(loaded)


def find_setting_spec(key: str) -> Optional[CameraSettingSpec]:
    for spec in SETTING_SPECS:
        if spec.key == key:
            return spec
    return None
