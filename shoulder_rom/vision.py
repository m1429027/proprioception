from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import cv2.aruco as aruco
import numpy as np

from .config import CalibrationConfig, ScreenConfig
from .models import DetectionResult, TrackbarValues

RED_DOMINANCE_DELTA = 25
AREA_IDEAL_MULTIPLIER = 3.0


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
    processed, gray, hsv = preprocess_frame(frame, values.ignore_bottom)

    _, mask_bright = cv2.threshold(gray, values.min_brightness, 255, cv2.THRESH_BINARY)
    lower_red1, upper_red1 = np.array([0, 100, 100]), np.array([10, 255, 255])
    lower_red2, upper_red2 = np.array([160, 100, 100]), np.array([180, 255, 255])
    mask_red_hsv = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)

    b_channel = processed[:, :, 0].astype(np.int16)
    g_channel = processed[:, :, 1].astype(np.int16)
    r_channel = processed[:, :, 2].astype(np.int16)
    red_dominant = np.where(
        (r_channel > g_channel + RED_DOMINANCE_DELTA)
        & (r_channel > b_channel + RED_DOMINANCE_DELTA),
        255,
        0,
    ).astype(np.uint8)

    mask_red = cv2.bitwise_and(mask_red_hsv, red_dominant)
    mask_core = cv2.bitwise_and(mask_red, mask_bright)
    kernel = np.ones((3, 3), np.uint8)
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_OPEN, kernel)
    mask_core = cv2.morphologyEx(mask_core, cv2.MORPH_OPEN, kernel)

    result = detect_best_candidate(processed, gray, mask_core, values)
    selected_mask = mask_core
    if result.camera_point is None:
        result = detect_best_candidate(processed, gray, mask_red, values)
        selected_mask = mask_red

    if result.camera_point is None:
        return DetectionResult(), gray, mask_red

    if homography_matrix is None:
        return result, gray, selected_mask

    screen_point = camera_to_screen(result.camera_point, homography_matrix)
    if screen_point is None:
        return result, gray, selected_mask

    sx, sy = screen_point
    in_bounds = 0 <= sx < screen.width and 0 <= sy < screen.height
    result.screen_point = screen_point if in_bounds else None
    result.in_screen_bounds = in_bounds
    return result, gray, selected_mask


def detect_best_candidate(
    frame: np.ndarray,
    gray: np.ndarray,
    mask: np.ndarray,
    values: TrackbarValues,
) -> DetectionResult:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return DetectionResult()

    best_result: Optional[DetectionResult] = None
    best_score = float("-inf")
    ideal_area = max(float(values.min_area) * AREA_IDEAL_MULTIPLIER, float(values.min_area) + 1.0)

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= values.min_area:
            continue

        center = contour_center(contour)
        if center is None:
            continue

        contour_mask = np.zeros_like(mask)
        cv2.drawContours(contour_mask, [contour], -1, 255, -1)
        mean_brightness = float(cv2.mean(gray, mask=contour_mask)[0])
        mean_bgr = cv2.mean(frame, mask=contour_mask)
        red_advantage = float(mean_bgr[2] - max(mean_bgr[1], mean_bgr[0]))

        perimeter = float(cv2.arcLength(contour, True))
        circularity = 0.0
        if perimeter > 0.0:
            circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))

        area_penalty = abs(area - ideal_area) / max(ideal_area, 1.0)
        score = (
            red_advantage * 4.0
            + mean_brightness * 1.5
            + circularity * 60.0
            - area_penalty * 50.0
            - area * 0.2
        )

        candidate = DetectionResult(
            camera_point=center,
            radius=float(cv2.minEnclosingCircle(contour)[1]),
            area=area,
        )

        if score > best_score:
            best_result = candidate
            best_score = score
            continue

        if (
            best_result is not None
            and abs(score - best_score) < 10.0
            and mean_brightness >= values.min_brightness
            and area < best_result.area
        ):
            best_result = candidate
            best_score = score

    return best_result if best_result is not None else DetectionResult()


def contour_center(contour: np.ndarray) -> Optional[Tuple[float, float]]:
    moments = cv2.moments(contour)
    if moments["m00"] != 0:
        return (
            float(moments["m10"] / moments["m00"]),
            float(moments["m01"] / moments["m00"]),
        )

    try:
        (cx, cy), _ = cv2.minEnclosingCircle(contour)
        return float(cx), float(cy)
    except cv2.error:
        return None


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
