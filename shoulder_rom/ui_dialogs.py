from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog


class DialogService:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.attributes("-topmost", True)

    def ask_scale_cm(self, current_value: float) -> Optional[float]:
        return simpledialog.askfloat(
            "Scale Settings",
            "Enter the real-world distance in centimeters represented by 50 projected pixels:",
            initialvalue=current_value,
            minvalue=0.1,
            parent=self.root,
        )

    def ask_segment_count(self, current_value: int) -> Optional[int]:
        return simpledialog.askinteger(
            "Segment Settings",
            "Enter how many segments should divide the path from START to END:",
            initialvalue=current_value,
            minvalue=2,
            parent=self.root,
        )

    def ask_practice_segment_end(
        self,
        current_end: int,
        max_segments: int,
    ) -> Optional[int]:
        return simpledialog.askinteger(
            "Practice Range",
            "Enter which segment to display from START:",
            initialvalue=current_end,
            minvalue=1,
            maxvalue=max_segments,
            parent=self.root,
        )

    def ask_exam_trial_count(self, current_value: int = 3) -> Optional[int]:
        return simpledialog.askinteger(
            "Exam Settings",
            "Enter how many trials to record:",
            initialvalue=current_value,
            minvalue=1,
            parent=self.root,
        )

    def choose_exam_xlsx_path(self, initial_dir: Optional[Path] = None) -> Optional[Path]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            title="Choose exam Excel file",
            initialdir=str(initial_dir) if initial_dir else None,
            initialfile="exam_trials_{0}.xlsx".format(timestamp),
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            parent=self.root,
        )
        return Path(path) if path else None

    def choose_csv_path(self, initial_dir: Optional[Path] = None) -> Optional[Path]:
        timestamp = datetime.now().strftime("%Y%m%d")
        path = filedialog.asksaveasfilename(
            title="Choose measurement CSV file",
            initialdir=str(initial_dir) if initial_dir else None,
            initialfile="shoulder_measurements_{0}.csv".format(timestamp),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self.root,
        )
        return Path(path) if path else None

    def show_warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self.root)

    def destroy(self) -> None:
        self.root.destroy()
