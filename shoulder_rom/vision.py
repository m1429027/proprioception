from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import cv2.aruco as aruco
import numpy as np

from .config import CalibrationConfig, ScreenConfig
from .models import DetectionResult, TrackbarValues

RED_DOMINANCE_DELTA = 25
AREA_IDEAL_MULTIPLIER = 3.0
CORE_BRIGHTNESS_DELTA = 18
CORE_MAX_AREA_MULTIPLIER = 12.0
CORE_MIN_PIXEL_COUNT = 3
RED_RING_DILATION_SIZE = 9
CORE_COLOR_SEARCH_RADIUS = 12
WHITE_CORE_CHANNEL_FLOOR = 210


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
    core_threshold = int(min(255, max(values.min_brightness + CORE_BRIGHTNESS_DELTA, 200)))
    _, mask_core_bright = cv2.threshold(gray, core_threshold, 255, cv2.THRESH_BINARY)
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
    white_core = np.where(
        (r_channel >= WHITE_CORE_CHANNEL_FLOOR)
        & (g_channel >= WHITE_CORE_CHANNEL_FLOOR - 20)
        & (b_channel >= WHITE_CORE_CHANNEL_FLOOR - 20),
        255,
        0,
    ).astype(np.uint8)

    mask_red = cv2.bitwise_and(mask_red_hsv, red_dominant)
    kernel = np.ones((3, 3), np.uint8)
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_OPEN, kernel)
    mask_bright = cv2.morphologyEx(mask_bright, cv2.MORPH_OPEN, kernel)
    mask_core_bright = cv2.morphologyEx(mask_core_bright, cv2.MORPH_OPEN, kernel)
    mask_core_bright = cv2.bitwise_or(mask_core_bright, cv2.bitwise_and(mask_bright, white_core))

    result = detect_best_candidate(processed, gray, mask_core_bright, mask_red, values)
    selected_mask = mask_core_bright
    if result.camera_point is None:
        fallback_mask = cv2.bitwise_and(mask_red, mask_bright)
        fallback_mask = cv2.morphologyEx(fallback_mask, cv2.MORPH_OPEN, kernel)
        result = detect_best_candidate(processed, gray, fallback_mask, mask_red, values)
        selected_mask = fallback_mask

    if result.camera_point is None:
        return DetectionResult(), gray, selected_mask

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
    core_mask: np.ndarray,
    red_mask: np.ndarray,
    values: TrackbarValues,
) -> DetectionResult:
    contours, _ = cv2.findContours(core_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return DetectionResult()

    best_result: Optional[DetectionResult] = None
    best_score = float("-inf")
    ideal_area = max(float(values.min_area) * AREA_IDEAL_MULTIPLIER, float(values.min_area) + 1.0)
    max_core_area = max(ideal_area * CORE_MAX_AREA_MULTIPLIER, ideal_area + 8.0)

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= values.min_area:
            continue
        if area > max_core_area:
            continue

        contour_mask = np.zeros_like(core_mask)
        cv2.drawContours(contour_mask, [contour], -1, 255, -1)
        center = core_center(frame, gray, contour_mask, contour)
        if center is None:
            continue

        mean_brightness = float(cv2.mean(gray, mask=contour_mask)[0])
        _, peak_brightness, _, _ = cv2.minMaxLoc(gray, mask=contour_mask)
        mean_bgr = cv2.mean(frame, mask=contour_mask)
        red_advantage = float(mean_bgr[2] - max(mean_bgr[1], mean_bgr[0]))
        ring_score = red_ring_score(red_mask, contour_mask, center)

        perimeter = float(cv2.arcLength(contour, True))
        circularity = 0.0
        if perimeter > 0.0:
            circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))

        area_penalty = abs(area - ideal_area) / max(ideal_area, 1.0)
        score = (
            peak_brightness * 2.2
            + mean_brightness * 0.6
            + ring_score * 140.0
            + red_advantage * 1.2
            + circularity * 60.0
            - area_penalty * 50.0
            - area * 0.6
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


def core_center(
    frame: np.ndarray,
    gray: np.ndarray,
    contour_mask: np.ndarray,
    contour: np.ndarray,
) -> Optional[Tuple[float, float]]:
    masked_gray = cv2.bitwise_and(gray, gray, mask=contour_mask)
    peak_value = int(masked_gray.max())
    if peak_value <= 0:
        return contour_center(contour)

    core_threshold = max(peak_value - 10, 0)
    core_pixels = np.where((masked_gray >= core_threshold) & (contour_mask > 0), 255, 0).astype(np.uint8)
    coords = np.column_stack(np.where(core_pixels > 0))
    if len(coords) < CORE_MIN_PIXEL_COUNT:
        return contour_center(contour)

    weights = masked_gray[coords[:, 0], coords[:, 1]].astype(np.float32)
    total_weight = float(weights.sum())
    if total_weight <= 0.0:
        return contour_center(contour)

    center_y = float(np.average(coords[:, 0], weights=weights))
    center_x = float(np.average(coords[:, 1], weights=weights))
    refined = refine_center_with_red_core(frame, center_x, center_y)
    if refined is not None:
        return refined
    return center_x, center_y


def refine_center_with_red_core(
    frame: np.ndarray,
    center_x: float,
    center_y: float,
) -> Optional[Tuple[float, float]]:
    height, width = frame.shape[:2]
    x0 = max(0, int(round(center_x)) - CORE_COLOR_SEARCH_RADIUS)
    x1 = min(width, int(round(center_x)) + CORE_COLOR_SEARCH_RADIUS + 1)
    y0 = max(0, int(round(center_y)) - CORE_COLOR_SEARCH_RADIUS)
    y1 = min(height, int(round(center_y)) + CORE_COLOR_SEARCH_RADIUS + 1)
    if x1 <= x0 or y1 <= y0:
        return None

    patch = frame[y0:y1, x0:x1].astype(np.float32)
    red_signal = patch[:, :, 2] - ((patch[:, :, 0] + patch[:, :, 1]) * 0.5)
    red_signal = np.clip(red_signal, 0.0, None)
    strong = red_signal > float(RED_DOMINANCE_DELTA)
    if not np.any(strong):
        return None

    yy, xx = np.where(strong)
    weights = red_signal[yy, xx]
    total_weight = float(weights.sum())
    if total_weight <= 0.0:
        return None

    refined_x = float(np.average(xx, weights=weights)) + x0
    refined_y = float(np.average(yy, weights=weights)) + y0
    return refined_x, refined_y


def red_ring_score(
    red_mask: np.ndarray,
    contour_mask: np.ndarray,
    center: Tuple[float, float],
) -> float:
    kernel_size = max(3, RED_RING_DILATION_SIZE)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    dilated = cv2.dilate(contour_mask, kernel, iterations=1)
    ring_mask = cv2.subtract(dilated, contour_mask)
    ring_pixels = int(cv2.countNonZero(ring_mask))
    if ring_pixels <= 0:
        return 0.0

    red_ring_pixels = int(cv2.countNonZero(cv2.bitwise_and(red_mask, ring_mask)))
    base_ratio = red_ring_pixels / float(ring_pixels)

    cx = int(round(center[0]))
    cy = int(round(center[1]))
    height, width = red_mask.shape[:2]
    x0 = max(0, cx - CORE_COLOR_SEARCH_RADIUS)
    x1 = min(width, cx + CORE_COLOR_SEARCH_RADIUS + 1)
    y0 = max(0, cy - CORE_COLOR_SEARCH_RADIUS)
    y1 = min(height, cy + CORE_COLOR_SEARCH_RADIUS + 1)
    local_red = red_mask[y0:y1, x0:x1]
    local_ratio = 0.0
    if local_red.size > 0:
        local_ratio = float(cv2.countNonZero(local_red)) / float(local_red.size)
    return max(base_ratio, local_ratio)


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
