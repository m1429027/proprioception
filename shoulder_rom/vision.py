from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import cv2.aruco as aruco
import numpy as np

from .config import CalibrationConfig, ScreenConfig
from .models import DetectionResult, TrackbarValues


def build_aruco() -> Tuple[cv2.aruco.Dictionary, cv2.aruco.DetectorParameters]:
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    try:
        parameters = aruco.DetectorParameters()
    except AttributeError:
        parameters = aruco.DetectorParameters_create()
    return dictionary, parameters


def open_camera(camera_id: int) -> cv2.VideoCapture:
    if hasattr(cv2, "CAP_DSHOW"):
        return cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
    return cv2.VideoCapture(camera_id)


def apply_camera_controls(cap: cv2.VideoCapture, values: TrackbarValues) -> None:
    cap.set(cv2.CAP_PROP_EXPOSURE, -1 * (13 - values.exposure))
    cap.set(cv2.CAP_PROP_FOCUS, values.focus)


def preprocess_frame(frame: np.ndarray, ignore_bottom: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    processed = frame.copy()
    height, width = processed.shape[:2]
    if ignore_bottom > 0:
        top = max(height - ignore_bottom, 0)
        cv2.rectangle(processed, (0, top), (width, height), (0, 0, 0), -1)

    gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(processed, cv2.COLOR_BGR2HSV)
    return processed, gray, hsv


def detect_laser(
    frame: np.ndarray,
    values: TrackbarValues,
    homography_matrix: Optional[np.ndarray],
    screen: ScreenConfig,
) -> Tuple[DetectionResult, np.ndarray, np.ndarray]:
    _, gray, hsv = preprocess_frame(frame, values.ignore_bottom)

    _, mask_bright = cv2.threshold(gray, values.min_brightness, 255, cv2.THRESH_BINARY)
    lower_red1, upper_red1 = np.array([0, 100, 100]), np.array([10, 255, 255])
    lower_red2, upper_red2 = np.array([160, 100, 100]), np.array([180, 255, 255])
    mask_red = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)
    mask = cv2.bitwise_or(mask_bright, mask_red)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return DetectionResult(), gray, mask

    largest = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(largest))
    if area <= values.min_area:
        return DetectionResult(area=area), gray, mask

    (cx, cy), radius = cv2.minEnclosingCircle(largest)
    result = DetectionResult(camera_point=(cx, cy), radius=float(radius), area=area)

    if homography_matrix is None:
        return result, gray, mask

    screen_point = camera_to_screen((cx, cy), homography_matrix)
    if screen_point is None:
        return result, gray, mask

    sx, sy = screen_point
    in_bounds = 0 <= sx < screen.width and 0 <= sy < screen.height
    result.screen_point = screen_point if in_bounds else None
    result.in_screen_bounds = in_bounds
    return result, gray, mask


def camera_to_screen(
    camera_point: Tuple[float, float],
    homography_matrix: np.ndarray,
) -> Optional[Tuple[int, int]]:
    try:
        point = np.array([[[camera_point[0], camera_point[1]]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, homography_matrix)
        return int(transformed[0][0][0]), int(transformed[0][0][1])
    except cv2.error:
        return None


def calibration_marker_layout(
    screen: ScreenConfig,
    calibration: CalibrationConfig,
) -> Dict[int, Tuple[int, int]]:
    margin = calibration.marker_margin
    size = calibration.marker_size
    return {
        0: (margin, margin),
        1: (screen.width - margin - size, margin),
        2: (screen.width - margin - size, screen.height - margin - size),
        3: (margin, screen.height - margin - size),
    }


def marker_centers(
    screen: ScreenConfig,
    calibration: CalibrationConfig,
) -> Dict[int, Tuple[float, float]]:
    size = calibration.marker_size
    return {
        marker_id: (x + size / 2, y + size / 2)
        for marker_id, (x, y) in calibration_marker_layout(screen, calibration).items()
    }


def compute_calibration_homography(
    gray_frame: np.ndarray,
    aruco_dict: cv2.aruco.Dictionary,
    aruco_params: cv2.aruco.DetectorParameters,
    screen: ScreenConfig,
    calibration: CalibrationConfig,
) -> Tuple[Optional[np.ndarray], str]:
    corners, ids, _ = aruco.detectMarkers(gray_frame, aruco_dict, parameters=aruco_params)
    if ids is None or len(ids) < 4:
        return None, "Calibration in progress: fewer than 4 ArUco markers detected."

    id_list = ids.flatten().tolist()
    required_ids = [0, 1, 2, 3]
    missing = [marker_id for marker_id in required_ids if marker_id not in id_list]
    if missing:
        return None, "Calibration in progress: missing marker(s) {0}.".format(missing)

    centers = marker_centers(screen, calibration)
    src_pts = []
    dst_pts = []
    for index, marker_id in enumerate(id_list):
        if marker_id not in centers:
            continue
        corner = corners[index][0]
        src_pts.append([float(np.mean(corner[:, 0])), float(np.mean(corner[:, 1]))])
        dst_pts.append(centers[marker_id])

    if len(src_pts) < 4:
        return None, "Calibration in progress: marker data is incomplete. Adjust the camera or projector."

    matrix, _ = cv2.findHomography(
        np.array(src_pts, dtype=np.float32),
        np.array(dst_pts, dtype=np.float32),
        cv2.RANSAC,
        5.0,
    )
    if matrix is None:
        return None, "Calibration failed: unable to build the homography matrix."

    return matrix, "Calibration successful. Projection mapping updated."
