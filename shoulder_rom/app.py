from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Optional

import cv2
import numpy as np

from .camera_panel import update_setting_value
from .config import AppConfig, CONTROL_WINDOW_NAME, PROJECTOR_WINDOW_NAME
from .models import (
    AppMode,
    AppState,
    ControlPanelLayout,
    DetectionResult,
    ExamPointRecord,
    ExamTrialRecord,
    MeasurementPhase,
    MeasurementRecord,
    PathCaptureRecord,
)
from .path_tools import process_measurement_path
from .platform_win import toggle_borderless
from .renderer import compute_measurement_metrics, render_control_view, render_projector_view
from .storage import (
    append_measurement_record,
    load_camera_settings,
    load_homography,
    save_exam_trials_workbook,
    save_path_capture,
    save_camera_settings,
    save_homography,
)
from .ui_dialogs import DialogService
from .vision import (
    apply_camera_controls,
    build_aruco,
    compute_calibration_homography,
    detect_laser,
    open_camera,
)


def nothing(_: int) -> None:
    pass


TOOLBAR_ACTION_MESSAGES = {
    "measurement": ("Measurement mode enabled.", "Measurement mode disabled."),
    "practice": ("Practice mode enabled.", "Practice mode disabled."),
    "exam": ("Exam mode enabled.", "Exam mode disabled."),
    "practice_range": ("Practice range updated.", None),
    "calibrate": ("Calibration mode enabled.", "Calibration mode disabled."),
    "reset": ("Start and end points cleared.", None),
    "save_csv": ("Measurement saved.", None),
    "scale": ("Scale updated.", None),
    "segments": ("Split count updated.", None),
    "fullscreen": ("Projector window fullscreen toggled.", None),
    "borderless": ("Projector window borderless mode toggled.", None),
    "settings": ("Camera settings opened.", "Camera settings hidden."),
}

SAMPLING_INTERVAL_EPSILON = 1e-6


class ShoulderMeasurementApp:
    def __init__(self, config: Optional[AppConfig] = None) -> None:
        self.config = config or AppConfig()
        try:
            self.aruco_dict, self.aruco_params = build_aruco()
        except (AttributeError, cv2.error) as exc:
            raise RuntimeError("Please install opencv-contrib-python to use ArUco calibration.") from exc

        homography_matrix, startup_message = load_homography(self.config.calibration.calibration_path)
        camera_settings, settings_message = load_camera_settings(
            self.config.settings.camera_settings_path,
            self.config.trackbars,
        )
        self.state = AppState(
            mode=AppMode.IDLE,
            homography_matrix=homography_matrix,
            calibrating=False,
            is_fullscreen=False,
            is_borderless=False,
            phase=MeasurementPhase.IDLE,
            start_point=None,
            end_point=None,
            scale_cm=self.config.default_scale_cm,
            segment_count=3,
            camera_settings=camera_settings,
            detection=DetectionResult(),
            practice_segment_start=1,
            practice_segment_end=3,
            latest_message="{0} {1}".format(startup_message, settings_message).strip(),
            control_panel_layout=ControlPanelLayout(),
        )

        self.dialogs = DialogService()
        self.cap = open_camera(self.config.camera.camera_id)
        self._configure_camera()
        self._setup_windows()

    def _configure_camera(self) -> None:
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.config.camera.target_fps)
        if self.config.camera.disable_autofocus:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

    def _setup_windows(self) -> None:
        cv2.namedWindow(CONTROL_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(CONTROL_WINDOW_NAME, 720, 540)
        cv2.setMouseCallback(CONTROL_WINDOW_NAME, self._handle_control_mouse)
        cv2.namedWindow(PROJECTOR_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(PROJECTOR_WINDOW_NAME, 960, 540)

    def run(self) -> None:
        print("=== Shoulder Laser Projection Measurement System ===")
        print("Space: mark start/end | Q: quit")
        print("Toolbar: Measure | Practice | Exam | Range | Calibrate | Reset | Save CSV | Scale | Split | Full | Border | Settings")
        print("Fallback shortcuts: C = calibrate, R = reset")

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    self.state.latest_message = "Cannot read camera frame. Check the camera connection."
                    break

                trackbars = self.state.camera_settings.to_trackbar_values()
                apply_camera_controls(self.cap, trackbars)
                detection, gray_frame, _ = detect_laser(
                    frame,
                    trackbars,
                    self.state.homography_matrix,
                    self.config.screen,
                )
                self.state.detection = detection
                self._capture_measurement_path_point()
                self._capture_exam_trial_point()

                if self.state.calibrating:
                    self._update_calibration(gray_frame)

                control_view, control_layout = render_control_view(
                    frame=frame,
                    state=self.state,
                    homography_ready=self.state.homography_matrix is not None,
                    latest_message=self.state.latest_message,
                )
                self.state.control_panel_layout = control_layout
                projector_view = render_projector_view(
                    state=self.state,
                    screen=self.config.screen,
                    calibration=self.config.calibration,
                    aruco_dict=self.aruco_dict,
                )

                cv2.imshow(CONTROL_WINDOW_NAME, control_view)
                cv2.imshow(PROJECTOR_WINDOW_NAME, projector_view)

                key = cv2.waitKey(1) & 0xFF
                if not self._handle_keypress(key):
                    break
        finally:
            self._save_camera_settings()
            self.cap.release()
            cv2.destroyAllWindows()
            self.dialogs.destroy()
            print("Program closed.")

    def _save_camera_settings(self) -> None:
        save_camera_settings(self.config.settings.camera_settings_path, self.state.camera_settings)

    def _handle_control_mouse(self, event: int, x: int, y: int, _flags: int, _param: object = None) -> None:
        if event != cv2.EVENT_LBUTTONDOWN or self.state.control_panel_layout is None:
            return

        layout = self.state.control_panel_layout
        for action, rect in layout.toolbar_button_rects.items():
            if point_in_rect(x, y, rect):
                self._handle_toolbar_action(action)
                return

        if not self.state.camera_settings.panel_visible:
            return

        for key, rect in layout.decrease_rects.items():
            if point_in_rect(x, y, rect):
                self.state.camera_settings = update_setting_value(self.state.camera_settings, key, -1)
                self.state.latest_message = "{0} adjusted to {1}.".format(
                    key.replace("_", " ").title(),
                    getattr(self.state.camera_settings, key),
                )
                self._save_camera_settings()
                return

        for key, rect in layout.increase_rects.items():
            if point_in_rect(x, y, rect):
                self.state.camera_settings = update_setting_value(self.state.camera_settings, key, 1)
                self.state.latest_message = "{0} adjusted to {1}.".format(
                    key.replace("_", " ").title(),
                    getattr(self.state.camera_settings, key),
                )
                self._save_camera_settings()
                return

    def _handle_toolbar_action(self, action: str) -> None:
        if action == "measurement":
            self.toggle_measurement_mode()
            return
        if action == "practice":
            self.toggle_practice_mode()
            return
        if action == "exam":
            self.toggle_exam_mode()
            return
        if action == "practice_range":
            self.update_practice_range()
            return
        if action == "calibrate":
            self.state.calibrating = not self.state.calibrating
            enabled_message, disabled_message = TOOLBAR_ACTION_MESSAGES[action]
            self.state.latest_message = enabled_message if self.state.calibrating else disabled_message
            return
        if action == "reset":
            self.reset_measurement()
            return
        if action == "save_csv":
            self.save_measurement()
            return
        if action == "scale":
            self.update_scale()
            return
        if action == "segments":
            self.update_segment_count()
            return
        if action == "fullscreen":
            self.state.is_fullscreen = not self.state.is_fullscreen
            cv2.setWindowProperty(
                PROJECTOR_WINDOW_NAME,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN if self.state.is_fullscreen else cv2.WINDOW_NORMAL,
            )
            self.state.latest_message = TOOLBAR_ACTION_MESSAGES[action][0]
            return
        if action == "borderless":
            self.state.is_borderless = toggle_borderless(PROJECTOR_WINDOW_NAME, self.state.is_borderless)
            self.state.latest_message = TOOLBAR_ACTION_MESSAGES[action][0]
            return
        if action == "settings":
            self.state.camera_settings.panel_visible = not self.state.camera_settings.panel_visible
            enabled_message, disabled_message = TOOLBAR_ACTION_MESSAGES[action]
            self.state.latest_message = enabled_message if self.state.camera_settings.panel_visible else disabled_message
            self._save_camera_settings()
            return

    def _update_calibration(self, gray_frame: np.ndarray) -> None:
        matrix, message = compute_calibration_homography(
            gray_frame=gray_frame,
            aruco_dict=self.aruco_dict,
            aruco_params=self.aruco_params,
            screen=self.config.screen,
            calibration=self.config.calibration,
        )
        self.state.latest_message = message
        if matrix is None:
            return

        self.state.homography_matrix = matrix
        save_homography(self.config.calibration.calibration_path, matrix)
        self.state.calibrating = False

    def _handle_keypress(self, key: int) -> bool:
        if key == 255:
            return True
        if key == ord("q"):
            return False
        if key == ord("c"):
            self._handle_toolbar_action("calibrate")
            return True
        if key == ord("r"):
            self._handle_toolbar_action("reset")
            return True
        if key == ord(" "):
            if self.state.mode == AppMode.EXAM:
                self.handle_exam_action()
            else:
                self.mark_current_point()
            return True
        return True

    def _capture_measurement_path_point(self) -> None:
        if self.state.mode != AppMode.MEASUREMENT:
            return
        if self.state.phase != MeasurementPhase.START_MARKED:
            return

        point = self.state.detection.screen_point
        if point is None:
            return
        now = perf_counter()
        if not self._sampling_due(self.state.measurement_last_sample_time, now):
            return
        self.state.measurement_last_sample_time = now
        if not self.state.raw_path_points or self.state.raw_path_points[-1] != point:
            self.state.raw_path_points.append(point)

    def _capture_exam_trial_point(self) -> None:
        if self.state.mode != AppMode.EXAM or not self.state.exam_recording:
            return
        if self.state.exam_trial_start_time is None:
            return

        point = self.state.detection.screen_point
        if point is None:
            return

        now = perf_counter()
        if not self._sampling_due(self.state.exam_last_sample_time, now):
            return
        self.state.exam_last_sample_time = now
        elapsed = now - self.state.exam_trial_start_time
        self.state.exam_current_points.append(
            ExamPointRecord(
                x=point[0],
                y=point[1],
                time_s=elapsed,
            )
        )

    def reset_measurement(self) -> None:
        self.state.start_point = None
        self.state.end_point = None
        self.state.phase = MeasurementPhase.IDLE
        self.state.mode = AppMode.IDLE
        self.state.raw_path_points = []
        self.state.filtered_path_points = []
        self.state.last_path_file = None
        self._reset_exam_state()
        self.state.latest_message = "Start and end points cleared."

    def _sampling_due(self, last_sample_time: Optional[float], now: float) -> bool:
        if last_sample_time is None:
            return True
        interval = 1.0 / max(self.config.camera.target_fps, 1.0)
        return (now - last_sample_time) + SAMPLING_INTERVAL_EPSILON >= interval

    def update_scale(self) -> None:
        new_scale = self.dialogs.ask_scale_cm(self.state.scale_cm)
        if new_scale is None:
            self.state.latest_message = "Scale update canceled."
            return
        self.state.scale_cm = new_scale
        self.state.latest_message = (
            "Scale updated: "
            f"{self.config.screen.scale_bar_pixels}px = {self.state.scale_cm:.1f} cm."
        )

    def update_segment_count(self) -> None:
        new_count = self.dialogs.ask_segment_count(self.state.segment_count)
        if new_count is None:
            self.state.latest_message = "Split count update canceled."
            return
        self.state.segment_count = new_count
        self.state.practice_segment_start = 1
        self.state.practice_segment_end = new_count
        self.state.latest_message = "Split count updated: {0} segment(s).".format(new_count)

    def update_practice_range(self) -> None:
        if not self.state.filtered_path_points:
            self.state.latest_message = "No measured path is available for practice."
            return

        selected = self.dialogs.ask_practice_segment_end(
            self.state.practice_segment_end,
            self.state.segment_count,
        )
        if selected is None:
            self.state.latest_message = "Practice range update canceled."
            return

        self.state.practice_segment_start = 1
        self.state.practice_segment_end = selected
        self.state.latest_message = "Practice range updated: START to segment {0}.".format(
            self.state.practice_segment_end,
        )

    def toggle_measurement_mode(self) -> None:
        if self.state.mode == AppMode.MEASUREMENT:
            self.state.mode = AppMode.IDLE
            if self.state.phase != MeasurementPhase.COMPLETE:
                self.state.phase = MeasurementPhase.IDLE
                self.state.start_point = None
                self.state.end_point = None
                self.state.raw_path_points = []
            self.state.latest_message = TOOLBAR_ACTION_MESSAGES["measurement"][1]
            return

        self.state.mode = AppMode.MEASUREMENT
        self._reset_exam_state()
        self.state.phase = MeasurementPhase.IDLE
        self.state.start_point = None
        self.state.end_point = None
        self.state.measurement_last_sample_time = None
        self.state.raw_path_points = []
        self.state.filtered_path_points = []
        self.state.practice_segment_start = 1
        self.state.practice_segment_end = self.state.segment_count
        self.state.latest_message = TOOLBAR_ACTION_MESSAGES["measurement"][0]

    def toggle_practice_mode(self) -> None:
        if not self.state.filtered_path_points:
            self.state.latest_message = "No measured path is available for practice."
            return

        if self.state.mode == AppMode.PRACTICE:
            self.state.mode = AppMode.IDLE
            self.state.latest_message = TOOLBAR_ACTION_MESSAGES["practice"][1]
            return

        self.state.mode = AppMode.PRACTICE
        self._reset_exam_state()
        self.state.latest_message = TOOLBAR_ACTION_MESSAGES["practice"][0]

    def toggle_exam_mode(self) -> None:
        if self.state.mode == AppMode.EXAM:
            self.state.mode = AppMode.IDLE
            self._reset_exam_state()
            self.state.latest_message = TOOLBAR_ACTION_MESSAGES["exam"][1]
            return

        if not self.state.filtered_path_points:
            self.state.latest_message = "No measured path is available for exam."
            return

        trial_count = self.dialogs.ask_exam_trial_count(3)
        if trial_count is None:
            self.state.latest_message = "Exam mode canceled."
            return

        self.state.mode = AppMode.EXAM
        self.state.raw_path_points = []
        self._reset_exam_state()
        self.state.exam_total_trials = trial_count
        self.state.exam_current_trial = 1
        self.state.latest_message = "Exam mode enabled. Trial 1 of {0} is ready.".format(trial_count)

    def handle_exam_action(self) -> None:
        if self.state.mode != AppMode.EXAM:
            self.state.latest_message = "Enable Exam mode before recording trials."
            return

        if self.state.exam_total_trials <= 0 or self.state.exam_current_trial <= 0:
            self.state.latest_message = "No exam session is active."
            return

        if not self.state.exam_recording:
            self.state.exam_recording = True
            self.state.exam_current_points = []
            self.state.exam_trial_start_time = perf_counter()
            self.state.exam_last_sample_time = None
            self._capture_exam_trial_point()
            self.state.latest_message = "Exam trial {0} recording started.".format(self.state.exam_current_trial)
            return

        total_time = 0.0
        if self.state.exam_trial_start_time is not None:
            total_time = perf_counter() - self.state.exam_trial_start_time
        self._capture_exam_trial_point()
        trial_record = ExamTrialRecord(
            trial_index=self.state.exam_current_trial,
            points=self.state.exam_current_points[:],
            total_time_s=total_time,
        )
        self.state.exam_trials.append(trial_record)
        self.state.exam_recording = False
        self.state.exam_trial_start_time = None
        self.state.exam_current_points = []

        if self.state.exam_current_trial >= self.state.exam_total_trials:
            self._finalize_exam_session()
            return

        completed_trial = self.state.exam_current_trial
        self.state.exam_current_trial += 1
        self.state.latest_message = "Exam trial {0} complete. Trial {1} is ready.".format(
            completed_trial,
            self.state.exam_current_trial,
        )

    def mark_current_point(self) -> None:
        if self.state.mode != AppMode.MEASUREMENT:
            self.state.latest_message = "Enable Measurement mode before marking points."
            return

        point = self.state.detection.screen_point
        if point is None:
            self.state.latest_message = "No valid projected point is available to mark."
            return

        if self.state.phase == MeasurementPhase.IDLE:
            self.state.start_point = point
            self.state.end_point = None
            self.state.phase = MeasurementPhase.START_MARKED
            self.state.measurement_last_sample_time = None
            self.state.raw_path_points = [point]
            self.state.filtered_path_points = []
            self.state.latest_message = f"Start point marked: {point}."
            return

        if self.state.phase == MeasurementPhase.START_MARKED:
            self.state.end_point = point
            if not self.state.raw_path_points or self.state.raw_path_points[-1] != point:
                self.state.raw_path_points.append(point)
            self.state.latest_message = "Processing measured path..."
            self._finalize_measurement_path()
            self.state.phase = MeasurementPhase.COMPLETE
            self.state.mode = AppMode.IDLE
            self.state.latest_message = f"End point marked: {point}. Path processed and ready for practice."
            return

        self.state.latest_message = "Measurement is already complete. Press R to reset."

    def _finalize_exam_session(self) -> None:
        default_path = self.config.exams.output_directory / "exam_trials_{0}.xlsx".format(
            datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        chosen_path = self.dialogs.choose_exam_xlsx_path(self.config.exams.output_directory)
        save_path = chosen_path if chosen_path is not None else default_path
        self.state.last_exam_file = save_exam_trials_workbook(save_path, self.state.exam_trials)
        trial_count = self.state.exam_total_trials
        self.state.mode = AppMode.IDLE
        self.state.exam_recording = False
        self.state.exam_trial_start_time = None
        self.state.exam_current_points = []
        self.state.exam_current_trial = trial_count
        self.state.latest_message = "Exam complete. Saved {0} trial(s) to {1}.".format(
            trial_count,
            self.state.last_exam_file.name,
        )

    def _reset_exam_state(self) -> None:
        self.state.exam_total_trials = 0
        self.state.exam_current_trial = 0
        self.state.exam_recording = False
        self.state.exam_trial_start_time = None
        self.state.measurement_last_sample_time = None
        self.state.exam_last_sample_time = None
        self.state.exam_current_points = []
        self.state.exam_trials = []
        self.state.last_exam_file = None

    def _finalize_measurement_path(self) -> None:
        if len(self.state.raw_path_points) < 2:
            self.state.filtered_path_points = self.state.raw_path_points[:]
            return

        filtered_path = process_measurement_path(
            self.state.raw_path_points,
            outlier_multiplier=self.config.paths.outlier_multiplier,
            minimum_jump_threshold=self.config.paths.minimum_jump_threshold,
            smoothing_window=self.config.paths.smoothing_window,
            resample_points_count=self.config.paths.resample_points,
        )
        self.state.filtered_path_points = filtered_path if filtered_path else self.state.raw_path_points[:]
        if self.state.start_point is not None and self.state.filtered_path_points:
            self.state.filtered_path_points[0] = self.state.start_point
        if self.state.end_point is not None and self.state.filtered_path_points:
            self.state.filtered_path_points[-1] = self.state.end_point
        self.state.practice_segment_start = 1
        self.state.practice_segment_end = self.state.segment_count

        record = PathCaptureRecord(
            timestamp=datetime.now(),
            raw_points=self.state.raw_path_points[:],
            filtered_points=self.state.filtered_path_points[:],
            segment_count=self.state.segment_count,
            scale_cm=self.state.scale_cm,
            scale_pixels=self.config.screen.scale_bar_pixels,
        )
        self.state.last_path_file = save_path_capture(self.config.paths.capture_directory, record)

    def save_measurement(self) -> None:
        if not self.state.measurement_ready:
            self.dialogs.show_warning("Measurement incomplete", "Mark both the start point and the end point before saving.")
            self.state.latest_message = "Measurement is incomplete. Save canceled."
            return

        if self.state.csv_path is None:
            chosen = self.dialogs.choose_csv_path(Path.cwd())
            if chosen is None:
                self.state.latest_message = "CSV save canceled."
                return
            self.state.csv_path = chosen

        metrics = compute_measurement_metrics(
            self.state.start_point,
            self.state.end_point,
            self.state.scale_cm,
            self.config.screen.scale_bar_pixels,
        )
        record = MeasurementRecord(
            timestamp=datetime.now(),
            start_x=self.state.start_point[0],
            start_y=self.state.start_point[1],
            end_x=self.state.end_point[0],
            end_y=self.state.end_point[1],
            total_cm=metrics.total_cm,
            one_third_cm=metrics.one_third_cm,
            two_third_cm=metrics.two_third_cm,
            scale_cm=self.state.scale_cm,
            scale_pixels=self.config.screen.scale_bar_pixels,
            calibration_file=self.config.calibration.calibration_path.name,
        )
        append_measurement_record(self.state.csv_path, record, self.config.csv_encoding)
        if self.state.last_path_file is not None:
            self.state.latest_message = "Measurement saved to {0}. Path saved to {1}.".format(
                self.state.csv_path.name,
                self.state.last_path_file.name,
            )
            return
        self.state.latest_message = f"Measurement saved to {self.state.csv_path.name}."


def main() -> None:
    app = ShoulderMeasurementApp()
    app.run()


def point_in_rect(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2
