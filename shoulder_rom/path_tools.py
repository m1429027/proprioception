from __future__ import annotations

import math
from typing import Optional

from .models import Point


def dedupe_consecutive_points(points: list[Point]) -> list[Point]:
    if not points:
        return []

    deduped = [points[0]]
    for point in points[1:]:
        if point != deduped[-1]:
            deduped.append(point)
    return deduped


def point_distance(point_a: Point, point_b: Point) -> float:
    dx = point_b[0] - point_a[0]
    dy = point_b[1] - point_a[1]
    return math.sqrt(dx * dx + dy * dy)


def cumulative_lengths(points: list[Point]) -> list[float]:
    if not points:
        return []

    lengths = [0.0]
    total = 0.0
    for index in range(1, len(points)):
        total += point_distance(points[index - 1], points[index])
        lengths.append(total)
    return lengths


def filter_extreme_points(
    points: list[Point],
    outlier_multiplier: float,
    minimum_jump_threshold: float,
) -> list[Point]:
    points = dedupe_consecutive_points(points)
    if len(points) <= 2:
        return points

    step_distances = [point_distance(points[index - 1], points[index]) for index in range(1, len(points))]
    positive_steps = sorted(distance for distance in step_distances if distance > 0)
    median_step = positive_steps[len(positive_steps) // 2] if positive_steps else 0.0
    jump_threshold = max(minimum_jump_threshold, median_step * outlier_multiplier)

    filtered = [points[0]]
    for point in points[1:]:
        if point_distance(filtered[-1], point) <= jump_threshold:
            filtered.append(point)
    if filtered[-1] != points[-1]:
        filtered.append(points[-1])
    return dedupe_consecutive_points(filtered)


def smooth_path(points: list[Point], window_size: int) -> list[Point]:
    if len(points) <= 2 or window_size <= 1:
        return points[:]

    half_window = max(window_size // 2, 1)
    smoothed: list[Point] = []
    for index in range(len(points)):
        if index == 0 or index == len(points) - 1:
            smoothed.append(points[index])
            continue
        start = max(0, index - half_window)
        end = min(len(points), index + half_window + 1)
        sample = points[start:end]
        avg_x = int(round(sum(point[0] for point in sample) / float(len(sample))))
        avg_y = int(round(sum(point[1] for point in sample) / float(len(sample))))
        smoothed.append((avg_x, avg_y))
    return dedupe_consecutive_points(smoothed)


def interpolate_point(point_a: Point, point_b: Point, ratio: float) -> Point:
    x = int(round(point_a[0] + (point_b[0] - point_a[0]) * ratio))
    y = int(round(point_a[1] + (point_b[1] - point_a[1]) * ratio))
    return (x, y)


def sample_point_at_fraction(points: list[Point], fraction: float) -> Optional[Point]:
    if not points:
        return None
    if len(points) == 1:
        return points[0]

    lengths = cumulative_lengths(points)
    total_length = lengths[-1]
    if total_length <= 0:
        return points[0]

    target_length = max(0.0, min(1.0, fraction)) * total_length
    for index in range(1, len(points)):
        if lengths[index] >= target_length:
            previous_length = lengths[index - 1]
            segment_length = max(lengths[index] - previous_length, 1e-6)
            ratio = (target_length - previous_length) / segment_length
            return interpolate_point(points[index - 1], points[index], ratio)
    return points[-1]


def resample_path(points: list[Point], target_points: int) -> list[Point]:
    points = dedupe_consecutive_points(points)
    if len(points) <= 1:
        return points[:]

    target_points = max(target_points, 2)
    sampled: list[Point] = []
    for index in range(target_points):
        fraction = index / float(target_points - 1)
        point = sample_point_at_fraction(points, fraction)
        if point is not None:
            sampled.append(point)
    return dedupe_consecutive_points(sampled)


def process_measurement_path(
    points: list[Point],
    outlier_multiplier: float,
    minimum_jump_threshold: float,
    smoothing_window: int,
    resample_points_count: int,
) -> list[Point]:
    filtered = filter_extreme_points(points, outlier_multiplier, minimum_jump_threshold)
    smoothed = smooth_path(filtered, smoothing_window)
    if len(smoothed) >= len(filtered):
        return smoothed
    return filtered


def slice_path_by_percentage(
    points: list[Point],
    segment_count: int,
    start_segment: int,
    end_segment: int,
) -> list[Point]:
    if not points:
        return []

    segment_count = max(segment_count, 1)
    start_segment = max(1, min(start_segment, segment_count))
    end_segment = max(start_segment, min(end_segment, segment_count))
    start_fraction = (start_segment - 1) / float(segment_count)
    end_fraction = end_segment / float(segment_count)

    lengths = cumulative_lengths(points)
    total_length = lengths[-1] if lengths else 0.0
    if total_length <= 0:
        return points[:]

    start_length = start_fraction * total_length
    end_length = end_fraction * total_length
    sliced: list[Point] = []

    start_point = sample_point_at_fraction(points, start_fraction)
    if start_point is not None:
        sliced.append(start_point)

    for index, point in enumerate(points[1:], start=1):
        if start_length <= lengths[index] <= end_length:
            sliced.append(point)

    end_point = sample_point_at_fraction(points, end_fraction)
    if end_point is not None:
        sliced.append(end_point)

    return dedupe_consecutive_points(sliced)
