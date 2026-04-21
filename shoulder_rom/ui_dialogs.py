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

    def ask_practice_segment_range(
        self,
        current_start: int,
        current_end: int,
        max_segments: int,
    ) -> Optional[tuple[int, int]]:
        start_segment = simpledialog.askinteger(
            "Practice Range",
            "Enter the first segment to display:",
            initialvalue=current_start,
            minvalue=1,
            maxvalue=max_segments,
            parent=self.root,
        )
        if start_segment is None:
            return None

        end_segment = simpledialog.askinteger(
            "Practice Range",
            "Enter the last segment to display:",
            initialvalue=max(current_end, start_segment),
            minvalue=start_segment,
            maxvalue=max_segments,
            parent=self.root,
        )
        if end_segment is None:
            return None

        return start_segment, end_segment

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
