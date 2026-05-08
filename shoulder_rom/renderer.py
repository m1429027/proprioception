from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import cv2
import cv2.aruco as aruco
import numpy as np

from .camera_panel import SETTING_SPECS
from .config import CalibrationConfig, ScreenConfig
from .models import AppMode, AppState, ControlPanelLayout, ExamTrialPhase, MeasurementMetrics, MeasurementPhase, Point, Rect
from .path_tools import sample_point_at_fraction, slice_path_by_percentage
from .vision import calibration_marker_layout


MODE_TABS = [
    ("initial", AppMode.INITIAL, "Init"),
    ("measurement", AppMode.MEASUREMENT, "Measure"),
    ("practice", AppMode.PRACTICE, "Practice"),
    ("exam", AppMode.EXAM, "Exam"),
]

MODE_ACTIONS = {
    AppMode.INITIAL: [
        ("calibrate", "Calibrate"),
        ("settings", "Settings"),
        ("scale", "Scale"),
        ("fullscreen", "Full"),
        ("borderless", "Border"),
        ("subject_folder", "Subject"),
    ],
    AppMode.MEASUREMENT: [
        ("reset_path", "Reset Path"),
        ("split", "Split"),
        ("save_path", "Save Path"),
    ],
    AppMode.PRACTICE: [
        ("practice_range", "Range"),
    ],
    AppMode.EXAM: [
        ("exam_range", "Range"),
        ("reset_trial", "Reset Trial"),
        ("save_exam", "Save Exam"),
    ],
}

RAW_PATH_COLOR = (255, 170, 60)
PROCESSED_PATH_COLOR = (255, 255, 0)
REFERENCE_BASE_PATH_COLOR = (90, 90, 90)
REFERENCE_SELECTED_PATH_COLOR = (255, 200, 80)


def render_control_view(
    frame: np.ndarray,
    state: AppState,
    homography_ready: bool,
    latest_message: str,
) -> tuple[np.ndarray, ControlPanelLayout]:
    control_view = frame.copy()
    height, width = control_view.shape[:2]
    ignore_y = max(height - state.camera_settings.ignore_bottom, 0)
    cv2.line(control_view, (0, ignore_y), (width, ignore_y), (0, 0, 255), 2)

    detection = state.detection
    if detection.camera_point is not None:
        color = (0, 255, 0) if detection.in_screen_bounds or not homography_ready else (0, 0, 255)
        cx, cy = int(detection.camera_point[0]), int(detection.camera_point[1])
        cv2.circle(control_view, (cx, cy), int(detection.radius + 10), color, 2)

    cv2.putText(control_view, f"Calibration: {'READY' if homography_ready else 'MISSING'}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(control_view, latest_message[:70], (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
    layout = draw_mode_tabs_and_actions(control_view, state, width)
    draw_measurement_prompt(control_view, state, width, height)
    draw_operator_help(control_view, state, width, height)
    draw_exam_error_panel(control_view, state, width, height)
    return control_view, layout


def render_projector_view(
    state: AppState,
    screen: ScreenConfig,
    calibration: CalibrationConfig,
    aruco_dict: Optional[cv2.aruco.Dictionary],
) -> np.ndarray:
    projector_view = np.zeros((screen.height, screen.width, 3), dtype=np.uint8)
    if state.calibrating:
        return render_calibration_view(projector_view, screen, calibration, aruco_dict)

    draw_scale_bar(projector_view, screen, state.scale_cm)
    draw_measurement(projector_view, state, screen)
    draw_reference_path_for_mode(projector_view, state)
    draw_crosshair(projector_view, state.detection.screen_point)
    return projector_view


def render_calibration_view(
    projector_view: np.ndarray,
    screen: ScreenConfig,
    calibration: CalibrationConfig,
    aruco_dict: Optional[cv2.aruco.Dictionary],
) -> np.ndarray:
    if aruco_dict is None:
        return projector_view

    positions = calibration_marker_layout(screen, calibration)
    size = calibration.marker_size
    for marker_id, (x, y) in positions.items():
        cv2.rectangle(projector_view, (x - 10, y - 10), (x + size + 10, y + size + 10), (255, 255, 255), -1)
        marker_img = aruco.generateImageMarker(aruco_dict, marker_id, size)
        projector_view[y:y + size, x:x + size] = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)

    return projector_view


def draw_scale_bar(projector_view: np.ndarray, screen: ScreenConfig, scale_cm: float) -> None:
    start_x, start_y = 50, screen.height - 50
    end_x = start_x + screen.scale_bar_pixels
    cv2.line(projector_view, (start_x, start_y), (end_x, start_y), (255, 255, 255), 3)
    cv2.line(projector_view, (start_x, start_y - 15), (start_x, start_y + 15), (255, 255, 255), 3)
    cv2.line(projector_view, (end_x, start_y - 15), (end_x, start_y + 15), (255, 255, 255), 3)
    cv2.putText(
        projector_view,
        f"Scale: {scale_cm:.1f} cm / {screen.scale_bar_pixels}px",
        (start_x, start_y - 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (200, 200, 200),
        2,
    )


def draw_measurement(projector_view: np.ndarray, state: AppState, screen: ScreenConfig) -> None:
    if state.start_point:
        cv2.circle(projector_view, state.start_point, 7, (255, 255, 0), -1)
        cv2.putText(projector_view, "START", (state.start_point[0] + 18, state.start_point[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2)

    if state.mode == AppMode.MEASUREMENT and len(state.raw_path_points) >= 2:
        draw_path_polyline(projector_view, state.raw_path_points, RAW_PATH_COLOR, 2)

    if state.phase == MeasurementPhase.COMPLETE and state.start_point and state.end_point:
        cv2.circle(projector_view, state.end_point, 7, (0, 255, 0), -1)
        cv2.putText(projector_view, "END", (state.end_point[0] + 18, state.end_point[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        path_points = state.filtered_path_points if len(state.filtered_path_points) >= 2 else [state.start_point, state.end_point]
        draw_path_polyline(projector_view, path_points, PROCESSED_PATH_COLOR, 2)

        metrics = compute_measurement_metrics(state.start_point, state.end_point, state.scale_cm, screen.scale_bar_pixels)
        cv2.putText(projector_view, f"MAX ROM: {metrics.total_cm:.1f} cm", (state.end_point[0] + 18, state.end_point[1] + 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, PROCESSED_PATH_COLOR, 2)
        draw_segment_markers(projector_view, path_points, state.segment_count)


def draw_reference_path_for_mode(projector_view: np.ndarray, state: AppState) -> None:
    if len(state.filtered_path_points) < 2:
        return

    if state.mode == AppMode.PRACTICE:
        draw_reference_path(projector_view, state.filtered_path_points, state.segment_count, state.practice_segment_end)
        return

    if state.mode == AppMode.EXAM:
        draw_reference_path(projector_view, state.filtered_path_points, state.segment_count, state.exam_segment_end)


def draw_reference_path(
    projector_view: np.ndarray,
    path_points: list[Point],
    segment_count: int,
    segment_end: int,
) -> None:
    draw_path_polyline(projector_view, path_points, REFERENCE_BASE_PATH_COLOR, 2)
    selected_path = slice_path_by_percentage(
        path_points,
        segment_count,
        1,
        segment_end,
    )
    if len(selected_path) >= 2:
        draw_path_polyline(projector_view, selected_path, REFERENCE_SELECTED_PATH_COLOR, 4)


def draw_crosshair(projector_view: np.ndarray, point: Optional[Point]) -> None:
    if point is None:
        return

    x, y = point
    cv2.line(projector_view, (x - 40, y), (x + 40, y), (0, 255, 0), 2)
    cv2.line(projector_view, (x, y - 40), (x, y + 40), (0, 255, 0), 2)
    cv2.circle(projector_view, (x, y), 20, (0, 255, 0), 2)


def draw_segment_markers(projector_view: np.ndarray, path_points: list[Point], segment_count: int) -> None:
    if segment_count < 2:
        return
    for index in range(1, segment_count):
        ratio = index / float(segment_count)
        label = "{0}%".format(int(ratio * 100))
        point = sample_point_at_fraction(path_points, ratio)
        previous_point = sample_point_at_fraction(path_points, max(0.0, ratio - 0.01))
        next_point = sample_point_at_fraction(path_points, min(1.0, ratio + 0.01))
        if point is None or previous_point is None or next_point is None:
            continue

        dx = next_point[0] - previous_point[0]
        dy = next_point[1] - previous_point[1]
        dist_px = math.sqrt(dx * dx + dy * dy)
        if dist_px <= 0:
            continue

        vx, vy = -dy / dist_px, dx / dist_px
        tick_length = 40
        px, py = point
        pt1 = (int(px + vx * tick_length), int(py + vy * tick_length))
        pt2 = (int(px - vx * tick_length), int(py - vy * tick_length))
        cv2.line(projector_view, pt1, pt2, (255, 255, 255), 3)
        cv2.putText(projector_view, label, (pt1[0] + 10, pt1[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)


def compute_measurement_metrics(
    start_point: Point,
    end_point: Point,
    scale_cm: float,
    scale_pixels: int,
) -> MeasurementMetrics:
    dx = end_point[0] - start_point[0]
    dy = end_point[1] - start_point[1]
    dist_px = math.sqrt(dx * dx + dy * dy)
    cm_per_px = scale_cm / max(scale_pixels, 1)
    total_cm = dist_px * cm_per_px
    return MeasurementMetrics(
        total_cm=total_cm,
        one_third_cm=total_cm / 3.0,
        two_third_cm=total_cm * 2.0 / 3.0,
    )


def draw_mode_tabs_and_actions(control_view: np.ndarray, state: AppState, width: int) -> ControlPanelLayout:
    layout = ControlPanelLayout()
    toolbar_x = 20
    tab_y = 84
    action_y = 126
    gap = 8

    tab_w = 88
    tab_h = 30
    draw_filled_rect(control_view, (toolbar_x - 8, tab_y - 10, min(width - 20, toolbar_x + 4 * (tab_w + gap)), tab_y + tab_h + 10), (25, 25, 25), 0.78)

    button_x = toolbar_x
    for action, mode, label in MODE_TABS:
        rect = (button_x, tab_y, button_x + tab_w, tab_y + tab_h)
        layout.mode_tab_rects[action] = rect
        active = state.mode == mode
        color = (86, 120, 70) if active else (70, 70, 70)
        draw_filled_rect(control_view, rect, color, 0.92)
        cv2.rectangle(control_view, (rect[0], rect[1]), (rect[2], rect[3]), (220, 220, 220), 1)
        cv2.putText(control_view, label, (rect[0] + 12, rect[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (255, 255, 255), 2)
        button_x += tab_w + gap

    actions = MODE_ACTIONS[state.mode]
    if actions:
        action_button_w = 110 if len(actions) <= 3 else 96
        action_button_h = 32
        action_x = toolbar_x
        background_right = action_x + len(actions) * (action_button_w + gap) - gap
        draw_filled_rect(control_view, (action_x - 8, action_y - 10, background_right + 8, action_y + action_button_h + 10), (25, 25, 25), 0.78)
        for action, label in actions:
            rect = (action_x, action_y, action_x + action_button_w, action_y + action_button_h)
            layout.action_button_rects[action] = rect
            color = (70, 70, 70)
            if action == "calibrate" and state.calibrating:
                color = (86, 120, 70)
            elif action == "fullscreen" and state.is_fullscreen:
                color = (86, 120, 70)
            elif action == "borderless" and state.is_borderless:
                color = (86, 120, 70)
            elif action == "settings" and state.camera_settings.panel_visible:
                color = (86, 120, 70)
            draw_filled_rect(control_view, rect, color, 0.92)
            cv2.rectangle(control_view, (rect[0], rect[1]), (rect[2], rect[3]), (220, 220, 220), 1)
            cv2.putText(control_view, label, (rect[0] + 8, rect[1] + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)
            action_x += action_button_w + gap

    if not state.camera_settings.panel_visible:
        return layout

    panel_x1 = width - 340
    panel_y1 = action_y + 56
    panel_x2 = width - 20
    panel_y2 = panel_y1 + 42 + (len(SETTING_SPECS) * 48) + 14
    draw_filled_rect(control_view, (panel_x1, panel_y1, panel_x2, panel_y2), (30, 30, 30), 0.82)
    cv2.rectangle(control_view, (panel_x1, panel_y1), (panel_x2, panel_y2), (180, 180, 180), 1)
    cv2.putText(control_view, "Camera Settings", (panel_x1 + 14, panel_y1 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

    row_y = panel_y1 + 50
    minus_left = panel_x2 - 106
    plus_left = panel_x2 - 52
    for spec in SETTING_SPECS:
        value = getattr(state.camera_settings, spec.key)
        cv2.putText(control_view, spec.label, (panel_x1 + 14, row_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 2)
        cv2.putText(control_view, str(value), (panel_x1 + 150, row_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 255, 255), 2)

        dec_rect = (minus_left, row_y - 2, minus_left + 34, row_y + 26)
        inc_rect = (plus_left, row_y - 2, plus_left + 34, row_y + 26)
        layout.decrease_rects[spec.key] = dec_rect
        layout.increase_rects[spec.key] = inc_rect

        draw_filled_rect(control_view, dec_rect, (65, 65, 65), 0.95)
        draw_filled_rect(control_view, inc_rect, (65, 65, 65), 0.95)
        cv2.rectangle(control_view, (dec_rect[0], dec_rect[1]), (dec_rect[2], dec_rect[3]), (180, 180, 180), 1)
        cv2.rectangle(control_view, (inc_rect[0], inc_rect[1]), (inc_rect[2], inc_rect[3]), (180, 180, 180), 1)
        cv2.putText(control_view, "-", (dec_rect[0] + 12, dec_rect[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(control_view, "+", (inc_rect[0] + 9, inc_rect[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        row_y += 48

    return layout


def draw_measurement_prompt(control_view: np.ndarray, state: AppState, width: int, height: int) -> None:
    prompt = measurement_phase_text(state)
    hint = operator_hint_text(state)
    box_rect = (20, height - 92, min(width - 20, 430), height - 18)
    draw_filled_rect(control_view, box_rect, (28, 28, 28), 0.8)
    cv2.rectangle(control_view, (box_rect[0], box_rect[1]), (box_rect[2], box_rect[3]), (180, 180, 180), 1)
    cv2.putText(control_view, prompt, (box_rect[0] + 14, box_rect[1] + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    cv2.putText(control_view, hint, (box_rect[0] + 14, box_rect[1] + 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 220, 255), 1)


def draw_operator_help(control_view: np.ndarray, state: AppState, width: int, height: int) -> None:
    subject_line = "Subject folder: not set"
    if state.subject_directory is not None:
        subject_line = "Subject folder: {0}".format(state.subject_directory.name)

    lines = [subject_line]
    if state.mode == AppMode.INITIAL:
        lines.extend([
            "Initial mode: calibration, scale, projector window, and subject folder.",
            "Use Settings to tune the camera only when needed.",
        ])
    elif state.mode == AppMode.MEASUREMENT:
        lines.extend([
            "Measurement: Space marks START, then END.",
            "Reset Path clears only the measurement path.",
            "Split changes how many equal sections divide the path.",
        ])
    elif state.mode == AppMode.PRACTICE:
        lines.extend([
            "Practice: Range shows START to the selected segment.",
            "Follow the highlighted reference path on the projector.",
            "Practice range: START to segment {0}".format(state.practice_segment_end),
        ])
    else:
        lines.extend([
            "Exam: Space marks start, then target, then end.",
            "Reset Trial clears only the current trial in progress.",
            "Save Exam exports the Excel file after all trials finish.",
            "Exam range: START to segment {0}".format(state.exam_segment_end),
            "Exam range set: {0}".format("Yes" if state.exam_range_confirmed else "No"),
            "Trial status: {0}".format(exam_status_line(state)),
        ])

    box_width = min(470, width - 40)
    box_height = 56 + len(lines) * 24
    box_rect = (20, height - box_height - 108, 20 + box_width, height - 108)
    draw_filled_rect(control_view, box_rect, (28, 28, 28), 0.8)
    cv2.rectangle(control_view, (box_rect[0], box_rect[1]), (box_rect[2], box_rect[3]), (180, 180, 180), 1)
    cv2.putText(control_view, "Control Panel Help", (box_rect[0] + 14, box_rect[1] + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    for index, line in enumerate(lines):
        cv2.putText(
            control_view,
            line[:98],
            (box_rect[0] + 14, box_rect[1] + 50 + index * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (210, 210, 210),
            1,
        )


def draw_exam_error_panel(control_view: np.ndarray, state: AppState, width: int, height: int) -> None:
    if state.mode != AppMode.EXAM and state.latest_exam_error_trial is None:
        return
    if state.latest_exam_error_trial is None or state.latest_exam_error_segment is None:
        return

    lines = [
        "Segment {0}, Trial {1}".format(
            state.latest_exam_error_segment,
            state.latest_exam_error_trial,
        ),
        "Start error: {0}".format(format_error_value(state.latest_exam_start_error_cm)),
        "Target error: {0}".format(format_error_value(state.latest_exam_target_error_cm)),
        "End error: {0}".format(format_error_value(state.latest_exam_end_error_cm)),
    ]
    box_width = min(360, width - 40)
    box_height = 40 + len(lines) * 24
    box_rect = (width - box_width - 20, 20, width - 20, 20 + box_height)
    draw_filled_rect(control_view, box_rect, (24, 38, 24), 0.84)
    cv2.rectangle(control_view, (box_rect[0], box_rect[1]), (box_rect[2], box_rect[3]), (170, 220, 170), 1)
    cv2.putText(control_view, "Exam Trial Error", (box_rect[0] + 14, box_rect[1] + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
    for index, line in enumerate(lines):
        cv2.putText(
            control_view,
            line,
            (box_rect[0] + 14, box_rect[1] + 50 + index * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (220, 255, 220),
            1,
        )


def measurement_phase_text(state: AppState) -> str:
    if state.mode == AppMode.EXAM:
        if state.exam_waiting_for_save:
            return "Exam complete"
        if not state.exam_range_confirmed:
            return "Exam: set RANGE first"
        if state.exam_phase == ExamTrialPhase.RECORDING_TO_TARGET:
            return "Exam: mark TARGET"
        if state.exam_phase == ExamTrialPhase.RECORDING_TO_END:
            return "Exam: mark END"
        if state.exam_total_trials > 0 and state.exam_current_trial > 0:
            return "Exam ready: mark START"
        return "Select Exam mode to start"
    if state.mode == AppMode.PRACTICE:
        return "Practice mode active"
    if state.mode == AppMode.INITIAL:
        return "Initial setup mode"
    if state.phase == MeasurementPhase.IDLE:
        return "Ready to mark START"
    if state.phase == MeasurementPhase.START_MARKED:
        return "Ready to mark END"
    return "Measurement complete"


def operator_hint_text(state: AppState) -> str:
    if state.mode == AppMode.MEASUREMENT:
        return "Subject action: press Space once."
    if state.mode == AppMode.PRACTICE:
        return "Subject action: follow the displayed path."
    if state.mode == AppMode.EXAM:
        if not state.exam_range_confirmed:
            return "Operator action: choose Exam range before recording."
        return "Subject action: press Space for START, TARGET, END."
    return "Operator action: set calibration, scale, and subject folder."


def exam_status_line(state: AppState) -> str:
    if state.exam_waiting_for_save:
        return "All trials complete, waiting for Save Exam"
    if not state.exam_range_confirmed:
        return "Waiting for Exam range selection"
    if state.exam_phase == ExamTrialPhase.RECORDING_TO_TARGET:
        return "Trial {0}/{1}: waiting for target point".format(
            state.exam_current_trial,
            state.exam_total_trials,
        )
    if state.exam_phase == ExamTrialPhase.RECORDING_TO_END:
        return "Trial {0}/{1}: waiting for end point".format(
            state.exam_current_trial,
            state.exam_total_trials,
        )
    if state.exam_total_trials > 0 and state.exam_current_trial > 0:
        return "Trial {0}/{1}: ready for start point".format(state.exam_current_trial, state.exam_total_trials)
    return "No active exam session"


def format_error_value(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return "{0:.3f} cm".format(value)


def draw_filled_rect(image: np.ndarray, rect: Rect, color: tuple[int, int, int], alpha: float) -> None:
    overlay = image.copy()
    x1, y1, x2, y2 = rect
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, image, 1.0 - alpha, 0, image)


def draw_path_polyline(projector_view: np.ndarray, points: list[Point], color: tuple[int, int, int], thickness: int) -> None:
    if len(points) < 2:
        return

    polyline = np.array(points, dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(projector_view, [polyline], False, color, thickness, cv2.LINE_AA)
