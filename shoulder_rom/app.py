from __future__ import annotations

from datetime import datetime
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
    PathCaptureRecord,
)
from .path_tools import process_measurement_path
from .platform_win import toggle_borderless
from .renderer import render_control_view, render_projector_view
from .storage import (
    load_camera_settings,
    load_homography,
    save_camera_settings,
    save_exam_trials_workbook,
    save_homography,
    save_path_capture,
)
from .ui_dialogs import DialogService
from .vision import (
    apply_camera_controls,
    build_aruco,
    compute_calibration_homography,
    detect_laser,
    open_camera,
)


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
            mode=AppMode.INITIAL,
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
            practice_segment_end=3,
            exam_segment_end=3,
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
        print("Mode tabs: Initial | Measure | Practice | Exam")
        print("Measurement: Space = mark START / END")
        print("Exam: Space = start / stop current trial")
        print("Fallback keys: C = calibrate | Q = quit")

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
        for action, rect in layout.mode_tab_rects.items():
            if point_in_rect(x, y, rect):
                self._handle_mode_tab(action)
                return

        for action, rect in layout.action_button_rects.items():
            if point_in_rect(x, y, rect):
                self._handle_action_button(action)
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

    def _handle_mode_tab(self, action: str) -> None:
        target_mode = {
            "initial": AppMode.INITIAL,
            "measurement": AppMode.MEASUREMENT,
            "practice": AppMode.PRACTICE,
            "exam": AppMode.EXAM,
        }.get(action)
        if target_mode is None:
            return

        if self.state.exam_recording and target_mode != AppMode.EXAM:
            self.state.latest_message = "Finish or reset the current exam trial before leaving Exam mode."
            return
        if (
            self.state.mode == AppMode.MEASUREMENT
            and self.state.phase == MeasurementPhase.START_MARKED
            and target_mode != AppMode.MEASUREMENT
        ):
            self.state.latest_message = "Finish or reset the current path before leaving Measurement mode."
            return

        if target_mode == AppMode.INITIAL:
            self.state.mode = AppMode.INITIAL
            self.state.latest_message = "Initial mode active."
            return

        if self.state.subject_directory is None:
            self.state.latest_message = "Please choose or create the subject folder before starting the next step."
            self.dialogs.show_warning(
                "Subject Folder",
                "Please choose or create the subject folder in Initial mode before using Measurement, Practice, or Exam.",
            )
            return

        if target_mode == AppMode.MEASUREMENT:
            self.state.mode = AppMode.MEASUREMENT
            if self.state.phase == MeasurementPhase.COMPLETE:
                if self._path_saved_ready():
                    self.state.latest_message = "Measurement mode active. Existing path is saved and ready."
                else:
                    self.state.latest_message = "Measurement mode active. Save Path before Practice or Exam."
            else:
                self.state.latest_message = "Measurement mode active. Press Space to mark START."
            return

        if target_mode == AppMode.PRACTICE:
            if not self._path_saved_ready():
                self.state.latest_message = "Save Path before entering Practice mode."
                return
            self.state.mode = AppMode.PRACTICE
            self.state.latest_message = "Practice mode active."
            return

        self._activate_exam_mode()

    def _handle_action_button(self, action: str) -> None:
        if action == "calibrate":
            self.state.calibrating = not self.state.calibrating
            self.state.latest_message = (
                "Calibration mode enabled." if self.state.calibrating else "Calibration mode disabled."
            )
            return
        if action == "settings":
            self.state.camera_settings.panel_visible = not self.state.camera_settings.panel_visible
            self.state.latest_message = (
                "Camera settings opened." if self.state.camera_settings.panel_visible else "Camera settings hidden."
            )
            self._save_camera_settings()
            return
        if action == "scale":
            self.update_scale()
            return
        if action == "fullscreen":
            self.state.is_fullscreen = not self.state.is_fullscreen
            cv2.setWindowProperty(
                PROJECTOR_WINDOW_NAME,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN if self.state.is_fullscreen else cv2.WINDOW_NORMAL,
            )
            self.state.latest_message = "Projector fullscreen toggled."
            return
        if action == "borderless":
            self.state.is_borderless = toggle_borderless(PROJECTOR_WINDOW_NAME, self.state.is_borderless)
            self.state.latest_message = "Projector borderless mode toggled."
            return
        if action == "subject_folder":
            self.choose_subject_directory()
            return
        if action == "reset_path":
            self.reset_path()
            return
        if action == "split":
            self.update_segment_count()
            return
        if action == "save_path":
            self.save_path()
            return
        if action == "practice_range":
            self.update_practice_range()
            return
        if action == "exam_range":
            self.update_exam_range()
            return
        if action == "reset_trial":
            self.reset_current_exam_trial()
            return
        if action == "save_exam":
            self.save_exam()
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
            self._handle_action_button("calibrate")
            return True
        if key == ord(" "):
            if self.state.mode == AppMode.EXAM:
                self.handle_exam_action()
            elif self.state.mode == AppMode.MEASUREMENT:
                self.mark_current_point()
            else:
                self.state.latest_message = "Space is only used in Measurement or Exam mode."
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

    def _sampling_due(self, last_sample_time: Optional[float], now: float) -> bool:
        if last_sample_time is None:
            return True
        interval = 1.0 / max(self.config.camera.target_fps, 1.0)
        return (now - last_sample_time) + SAMPLING_INTERVAL_EPSILON >= interval

    def choose_subject_directory(self) -> None:
        subject_dir = self.dialogs.choose_or_create_subject_directory(self.config.subjects.root_directory)
        if subject_dir is None:
            self.state.latest_message = "Subject folder selection canceled."
            return
        self.state.subject_directory = subject_dir
        self.state.latest_message = "Subject folder set to {0}.".format(subject_dir.name)

    def update_scale(self) -> None:
        new_scale = self.dialogs.ask_scale_cm(self.state.scale_cm)
        if new_scale is None:
            self.state.latest_message = "Scale update canceled."
            return
        self.state.scale_cm = new_scale
        if self.state.measurement_ready:
            self.state.last_path_file = None
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
        self.state.practice_segment_end = min(max(1, self.state.practice_segment_end), new_count)
        self.state.exam_segment_end = min(max(1, self.state.exam_segment_end), new_count)
        if self.state.measurement_ready:
            self.state.last_path_file = None
            self.state.latest_message = "Split count updated: {0} segment(s). Save Path again before Practice or Exam.".format(new_count)
            return
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

        self.state.practice_segment_end = selected
        self.state.latest_message = "Practice range updated: START to segment {0}.".format(selected)

    def update_exam_range(self) -> None:
        if not self.state.filtered_path_points:
            self.state.latest_message = "No measured path is available for exam."
            return

        selected = self.dialogs.ask_exam_segment_end(
            self.state.exam_segment_end,
            self.state.segment_count,
        )
        if selected is None:
            self.state.latest_message = "Exam range update canceled."
            return

        self.state.exam_segment_end = selected
        self.state.latest_message = "Exam range updated: START to segment {0}.".format(selected)

    def _activate_exam_mode(self) -> None:
        if not self._path_saved_ready():
            self.state.latest_message = "Save Path before entering Exam mode."
            return

        previous_mode = self.state.mode
        self.state.mode = AppMode.EXAM
        if self._exam_session_exists():
            self.state.latest_message = self._exam_status_message()
            return

        trial_count = self.dialogs.ask_exam_trial_count(3)
        if trial_count is None:
            self.state.mode = previous_mode
            self.state.latest_message = "Exam mode canceled."
            return

        self._start_new_exam_session(trial_count)
        self.state.latest_message = "Exam mode enabled. Trial 1 of {0} is ready.".format(trial_count)

    def _start_new_exam_session(self, trial_count: int) -> None:
        self.state.exam_total_trials = trial_count
        self.state.exam_current_trial = 1
        self.state.exam_recording = False
        self.state.exam_waiting_for_save = False
        self.state.exam_trial_start_time = None
        self.state.exam_last_sample_time = None
        self.state.exam_current_points = []
        self.state.exam_trials = []
        self.state.last_exam_file = None

    def _exam_session_exists(self) -> bool:
        return (
            self.state.exam_total_trials > 0
            or self.state.exam_current_trial > 0
            or bool(self.state.exam_trials)
            or self.state.exam_waiting_for_save
        )

    def _exam_status_message(self) -> str:
        if self.state.exam_waiting_for_save:
            return "Exam complete. Use Save Exam to export the Excel file."
        if self.state.exam_recording:
            return "Exam trial {0} is recording.".format(self.state.exam_current_trial)
        if self.state.exam_current_trial > 0 and self.state.exam_total_trials > 0:
            return "Exam mode active. Trial {0} of {1} is ready.".format(
                self.state.exam_current_trial,
                self.state.exam_total_trials,
            )
        return "Exam mode active."

    def handle_exam_action(self) -> None:
        if self.state.mode != AppMode.EXAM:
            self.state.latest_message = "Enable Exam mode before recording trials."
            return
        if not self._exam_session_exists():
            self.state.latest_message = "Start an exam session before recording trials."
            return
        if self.state.exam_waiting_for_save:
            self.state.latest_message = "All trials are complete. Use Save Exam to export the Excel file."
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
        self.state.exam_last_sample_time = None
        self.state.exam_current_points = []

        if self.state.exam_current_trial >= self.state.exam_total_trials:
            self.state.exam_waiting_for_save = True
            self.state.latest_message = "All exam trials are complete. Use Save Exam to export the Excel file."
            return

        completed_trial = self.state.exam_current_trial
        self.state.exam_current_trial += 1
        self.state.latest_message = "Exam trial {0} complete. Trial {1} is ready.".format(
            completed_trial,
            self.state.exam_current_trial,
        )

    def reset_current_exam_trial(self) -> None:
        if self.state.mode != AppMode.EXAM and not self._exam_session_exists():
            self.state.latest_message = "No exam session is active."
            return
        if self.state.exam_waiting_for_save:
            if not self.state.exam_trials:
                self.state.latest_message = "No completed exam trial is available to reset."
                return
            removed_trial = self.state.exam_trials.pop()
            self.state.exam_waiting_for_save = False
            self.state.exam_current_trial = removed_trial.trial_index
            self.state.exam_recording = False
            self.state.exam_trial_start_time = None
            self.state.exam_last_sample_time = None
            self.state.exam_current_points = []
            self.state.latest_message = "Exam trial {0} reset. Ready to record again.".format(
                removed_trial.trial_index,
            )
            return

        if self.state.exam_recording:
            self.state.exam_recording = False
            self.state.exam_trial_start_time = None
            self.state.exam_last_sample_time = None
            self.state.exam_current_points = []
            self.state.latest_message = "Current exam trial {0} reset.".format(self.state.exam_current_trial)
            return

        if self.state.exam_trials:
            removed_trial = self.state.exam_trials.pop()
            self.state.exam_current_trial = removed_trial.trial_index
            self.state.exam_recording = False
            self.state.exam_trial_start_time = None
            self.state.exam_last_sample_time = None
            self.state.exam_current_points = []
            self.state.latest_message = "Exam trial {0} reset. Ready to record again.".format(
                removed_trial.trial_index,
            )
            return

        if self.state.exam_current_trial <= 0 or self.state.exam_total_trials <= 0:
            self.state.latest_message = "No exam trial is ready to reset."
            return

        self.state.exam_recording = False
        self.state.exam_trial_start_time = None
        self.state.exam_last_sample_time = None
        self.state.exam_current_points = []
        self.state.latest_message = "Current exam trial {0} reset.".format(self.state.exam_current_trial)

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
            self.state.last_path_file = None
            self.state.latest_message = "Start point marked: {0}.".format(point)
            return

        if self.state.phase == MeasurementPhase.START_MARKED:
            self.state.end_point = point
            if not self.state.raw_path_points or self.state.raw_path_points[-1] != point:
                self.state.raw_path_points.append(point)
            self.state.latest_message = "Processing measured path..."
            self._finalize_measurement_path()
            self.state.phase = MeasurementPhase.COMPLETE
            self.state.latest_message = "End point marked: {0}. Path processed. Save Path before Practice or Exam.".format(point)
            return

        self.state.latest_message = "Measurement is already complete. Use Reset Path to start again."

    def reset_path(self) -> None:
        self.state.start_point = None
        self.state.end_point = None
        self.state.phase = MeasurementPhase.IDLE
        self.state.raw_path_points = []
        self.state.filtered_path_points = []
        self.state.measurement_last_sample_time = None
        self.state.last_path_file = None
        self.state.latest_message = "Measurement path reset."

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
        self.state.practice_segment_end = min(self.state.segment_count, max(1, self.state.practice_segment_end))
        self.state.exam_segment_end = min(self.state.segment_count, max(1, self.state.exam_segment_end))
        self.state.last_path_file = None

    def save_path(self) -> None:
        if self.state.subject_directory is None:
            self.state.latest_message = "Please set the subject folder before saving the path."
            self.dialogs.show_warning("Subject Folder", "Please choose or create a subject folder first.")
            return
        if not self.state.measurement_ready or not self.state.filtered_path_points:
            self.state.latest_message = "No completed measurement path is available to save."
            return

        timestamp = datetime.now()
        path = self.state.subject_directory / "{0}_path.json".format(timestamp.strftime("%Y%m%d_%H%M%S"))
        record = PathCaptureRecord(
            timestamp=timestamp,
            raw_points=self.state.raw_path_points[:],
            filtered_points=self.state.filtered_path_points[:],
            segment_count=self.state.segment_count,
            scale_cm=self.state.scale_cm,
            scale_pixels=self.config.screen.scale_bar_pixels,
        )
        self.state.last_path_file = save_path_capture(path, record)
        self.state.latest_message = "Path saved to {0}.".format(self.state.last_path_file.name)

    def _path_saved_ready(self) -> bool:
        return bool(self.state.filtered_path_points) and self.state.last_path_file is not None

    def save_exam(self) -> None:
        if self.state.subject_directory is None:
            self.state.latest_message = "Please set the subject folder before saving the exam."
            self.dialogs.show_warning("Subject Folder", "Please choose or create a subject folder first.")
            return
        if not self.state.exam_waiting_for_save or not self.state.exam_trials:
            self.state.latest_message = "Complete the full exam session before saving the Excel file."
            return

        timestamp = datetime.now()
        save_path = self.state.subject_directory / "{0}_data.xlsx".format(timestamp.strftime("%Y%m%d_%H%M%S"))
        self.state.last_exam_file = save_exam_trials_workbook(save_path, self.state.exam_trials)
        self.state.latest_message = "Exam saved to {0}.".format(self.state.last_exam_file.name)
        self._clear_exam_session()

    def _clear_exam_session(self) -> None:
        self.state.exam_total_trials = 0
        self.state.exam_current_trial = 0
        self.state.exam_recording = False
        self.state.exam_waiting_for_save = False
        self.state.exam_trial_start_time = None
        self.state.exam_last_sample_time = None
        self.state.exam_current_points = []
        self.state.exam_trials = []


def main() -> None:
    app = ShoulderMeasurementApp()
    app.run()


def point_in_rect(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2
