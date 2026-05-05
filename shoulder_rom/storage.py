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
from .models import CameraSettings, ExamTrialRecord, MeasurementRecord, PathCaptureRecord


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


def save_exam_trials_workbook(path: Path, trials: list[ExamTrialRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_exam_rows(trials)
    worksheet_xml = build_exam_worksheet_xml(rows)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
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
    <sheet name="Exam Trials" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)

    return path


def build_exam_rows(trials: list[ExamTrialRecord]) -> list[list[object]]:
    if not trials:
        return [["No exam data"]]

    max_points = max((len(trial.points) for trial in trials), default=0)
    total_rows = max_points + 3
    total_columns = len(trials) * 4 - 1
    rows: list[list[object]] = [["" for _ in range(total_columns)] for _ in range(total_rows)]

    for trial_index, trial in enumerate(trials):
        column_offset = trial_index * 4
        rows[0][column_offset] = "Trial {0}".format(trial.trial_index)
        rows[1][column_offset] = "x"
        rows[1][column_offset + 1] = "y"
        rows[1][column_offset + 2] = "time"

        for point_index, point in enumerate(trial.points, start=2):
            rows[point_index][column_offset] = point.x
            rows[point_index][column_offset + 1] = point.y
            rows[point_index][column_offset + 2] = round(point.time_s, 3)

        total_row_index = max_points + 2
        rows[total_row_index][column_offset] = "total time"
        rows[total_row_index][column_offset + 2] = round(trial.total_time_s, 3)

    return rows


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
