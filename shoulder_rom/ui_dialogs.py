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

    def ask_exam_segment_end(
        self,
        current_end: int,
        max_segments: int,
    ) -> Optional[int]:
        return simpledialog.askinteger(
            "Exam Range",
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

    def choose_or_create_subject_directory(self, base_dir: Path) -> Optional[Path]:
        create_new = messagebox.askyesnocancel(
            "Subject Folder",
            "Create a new subject folder?\nYes = create new\nNo = choose existing",
            parent=self.root,
        )
        if create_new is None:
            return None

        base_dir.mkdir(parents=True, exist_ok=True)
        if create_new:
            while True:
                parent_dir = filedialog.askdirectory(
                    title="Choose parent directory for the subject folder",
                    initialdir=str(base_dir),
                    parent=self.root,
                )
                if not parent_dir:
                    return None

                selected_parent = Path(parent_dir)

                folder_name = simpledialog.askstring(
                    "Subject Folder",
                    "Enter the subject folder name:",
                    parent=self.root,
                )
                if folder_name is None:
                    return None

                folder_name = folder_name.strip()
                if not folder_name:
                    messagebox.showwarning(
                        "Subject Folder",
                        "Folder name cannot be empty.",
                        parent=self.root,
                    )
                    continue

                subject_dir = selected_parent / folder_name
                if subject_dir.exists():
                    messagebox.showwarning(
                        "Subject Folder",
                        "This subject folder already exists. Please choose a different name.",
                        parent=self.root,
                    )
                    continue

                subject_dir.mkdir(parents=True, exist_ok=False)
                return subject_dir

        selected = filedialog.askdirectory(
            title="Choose an existing subject folder",
            initialdir=str(base_dir),
            parent=self.root,
        )
        return Path(selected) if selected else None

    def show_warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self.root)

    def destroy(self) -> None:
        self.root.destroy()
