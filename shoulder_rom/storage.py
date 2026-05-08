from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from .camera_panel import camera_settings_from_dict, camera_settings_to_dict, create_default_camera_settings
from .config import TrackbarDefaults
from .models import CameraSettings, ExamSegmentRecord, ExamTrialRecord, MeasurementRecord, PathCaptureRecord


def load_homography(path: Path) -> Tuple[Optional[np.ndarray], str]:
    if not path.exists():
        return None, "Calibration file {0} was not found. Press C to run calibration.".format(path.name)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        matrix = np.array(data["homography"], dtype=np.float32)
        if matrix.shape != (3, 3):
            return None, "Calibration file format is invalid. Please recalibrate."
        return matrix, "Calibration file {0} loaded.".format(path.name)
    except (OSError, ValueError, KeyError, TypeError):
        return None, "Unable to read the calibration file. Please recalibrate."


def save_homography(path: Path, matrix: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"homography": matrix.tolist()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_measurement_record(path: Path, record: MeasurementRecord, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding=encoding) as csv_file:
        writer = csv.writer(csv_file)
        if needs_header:
            writer.writerow(MeasurementRecord.csv_headers())
        writer.writerow(record.csv_row())


def save_path_capture(path: Path, record: PathCaptureRecord) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_camera_settings(path: Path, defaults: TrackbarDefaults) -> Tuple[CameraSettings, str]:
    if not path.exists():
        return create_default_camera_settings(defaults), "Using default camera settings."

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = camera_settings_from_dict(data, defaults)
        return settings, "Loaded saved camera settings."
    except (OSError, ValueError, TypeError):
        return create_default_camera_settings(defaults), "Camera settings file is invalid. Using defaults."


def save_camera_settings(path: Path, settings: CameraSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(camera_settings_to_dict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_exam_trials_workbook(
    path: Path,
    segments: list[ExamSegmentRecord],
    reference_path_points: Optional[list[tuple[int, int]]] = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_entries = build_exam_sheet_entries(segments, reference_path_points or [])
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{0}
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""".format(
                "".join(
                    '  <Override PartName="/xl/worksheets/sheet{0}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'.format(index + 1)
                    for index in range(len(sheet_entries))
                )
            ),
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "docProps/app.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>OpenAI Codex</Application>
</Properties>""",
        )
        archive.writestr(
            "docProps/core.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Exam Trials</dc:title>
  <dc:creator>OpenAI Codex</dc:creator>
  <cp:lastModifiedBy>OpenAI Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{0}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{0}</dcterms:modified>
</cp:coreProperties>""".format(created),
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
{0}
  </sheets>
</workbook>""".format(
                "".join(
                    '    <sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>\n'.format(
                        escape_sheet_name(name),
                        index + 1,
                    )
                    for index, (name, _) in enumerate(sheet_entries)
                )
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{0}
</Relationships>""".format(
                "".join(
                    '  <Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{0}.xml"/>\n'.format(index + 1)
                    for index in range(len(sheet_entries))
                )
            ),
        )
        for index, (_, rows) in enumerate(sheet_entries, start=1):
            archive.writestr("xl/worksheets/sheet{0}.xml".format(index), build_exam_worksheet_xml(rows))

    return path


def build_exam_sheet_entries(
    segments: list[ExamSegmentRecord],
    reference_path_points: list[tuple[int, int]],
) -> list[tuple[str, list[list[object]]]]:
    sheet_entries: list[tuple[str, list[list[object]]]] = []
    for segment in segments:
        sheet_entries.append(
            (
                "Segment {0}".format(segment.segment_end),
                build_segment_rows(segment),
            )
        )
    sheet_entries.append(("Path", build_path_rows(reference_path_points)))
    return sheet_entries


def build_segment_rows(segment: ExamSegmentRecord) -> list[list[object]]:
    trials = segment.trials
    if not trials:
        return [["No exam data"]]

    max_points = max((len(trial.points) for trial in trials), default=0)
    summary_rows_per_trial = 7
    total_rows = max_points + summary_rows_per_trial + 2
    total_columns = len(trials) * 6
    rows: list[list[object]] = [["" for _ in range(total_columns)] for _ in range(total_rows)]

    for trial_index, trial in enumerate(trials):
        column_offset = trial_index * 6
        rows[0][column_offset] = "Trial {0}".format(trial.trial_index)
        rows[1][column_offset] = "x"
        rows[1][column_offset + 1] = "y"
        rows[1][column_offset + 2] = "time"
        rows[1][column_offset + 3] = "event"
        rows[1][column_offset + 4] = "error_cm"

        for point_index, point in enumerate(trial.points, start=2):
            rows[point_index][column_offset] = point.x
            rows[point_index][column_offset + 1] = point.y
            rows[point_index][column_offset + 2] = round(point.time_s, 3)
            rows[point_index][column_offset + 3] = classify_exam_point_event(trial, point.time_s)

        summary_start = max_points + 3
        rows[summary_start][column_offset] = "start point"
        write_event_summary_row(
            rows[summary_start],
            column_offset,
            trial.start_point,
            trial.start_time_s,
        )
        rows[summary_start][column_offset + 5] = "start error"
        rows[summary_start][column_offset + 4] = format_error(trial.start_error_cm)

        rows[summary_start + 1][column_offset] = "target point"
        write_event_summary_row(
            rows[summary_start + 1],
            column_offset,
            trial.target_point,
            trial.target_time_s,
        )
        rows[summary_start + 1][column_offset + 5] = "target error"
        rows[summary_start + 1][column_offset + 4] = format_error(trial.target_error_cm)

        rows[summary_start + 2][column_offset] = "end point"
        write_event_summary_row(
            rows[summary_start + 2],
            column_offset,
            trial.end_point,
            trial.end_time_s,
        )
        rows[summary_start + 2][column_offset + 5] = "end error"
        rows[summary_start + 2][column_offset + 4] = format_error(trial.end_error_cm)

        rows[summary_start + 3][column_offset] = "total time"
        rows[summary_start + 3][column_offset + 3] = round(trial.total_time_s, 3)

    return rows


def build_path_rows(reference_path_points: list[tuple[int, int]]) -> list[list[object]]:
    if not reference_path_points:
        return [["No path data"]]
    rows: list[list[object]] = [["Path", "", ""], ["x", "y", ""]]
    for point in reference_path_points:
        rows.append([point[0], point[1], ""])
    return rows


def write_event_summary_row(
    row: list[object],
    column_offset: int,
    point: Optional[tuple[int, int]],
    time_s: Optional[float],
) -> None:
    if point is not None:
        row[column_offset + 1] = point[0]
        row[column_offset + 2] = point[1]
    if time_s is not None:
        row[column_offset + 3] = round(time_s, 3)


def format_error(value: Optional[float]) -> str:
    if value is None:
        return ""
    return "{0:.3f} cm".format(value)


def escape_sheet_name(value: str) -> str:
    return escape(value)


def classify_exam_point_event(trial: ExamTrialRecord, time_s: float) -> str:
    if trial.start_time_s is not None and abs(time_s - trial.start_time_s) < 1e-6:
        return "start"
    if trial.target_time_s is not None and abs(time_s - trial.target_time_s) < 1e-3:
        return "target"
    if trial.end_time_s is not None and abs(time_s - trial.end_time_s) < 1e-3:
        return "end"
    return ""


def build_exam_worksheet_xml(rows: list[list[object]]) -> str:
    row_xml_parts = []
    for row_index, row in enumerate(rows, start=1):
        cell_xml_parts = []
        for column_index, value in enumerate(row, start=1):
            if value == "":
                continue
            cell_reference = "{0}{1}".format(column_letter(column_index), row_index)
            if isinstance(value, str):
                cell_xml_parts.append(
                    '<c r="{0}" t="inlineStr"><is><t>{1}</t></is></c>'.format(
                        cell_reference,
                        escape(value),
                    )
                )
            else:
                cell_xml_parts.append(
                    '<c r="{0}"><v>{1}</v></c>'.format(
                        cell_reference,
                        value,
                    )
                )
        if cell_xml_parts:
            row_xml_parts.append('<row r="{0}">{1}</row>'.format(row_index, "".join(cell_xml_parts)))

    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{0}</sheetData>
</worksheet>""".format("".join(row_xml_parts))


def column_letter(index: int) -> str:
    letters = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))
