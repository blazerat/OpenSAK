"""
src/opensak/gui/dialogs/file_export_dialog.py — Export caches to GPX, LOC or GGZ file.

Simple dialog that lets the user choose a file format and destination path,
then writes the selected format using the generators in opensak.gps.garmin.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore    import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QRadioButton,
    QButtonGroup, QGroupBox, QProgressBar,
    QTextEdit,
)

from opensak.lang import tr
from opensak.gui.icon import OpenSAKMessageBox as QMessageBox
from opensak.gui.dialogs import make_progress_cb


# ── Background worker ─────────────────────────────────────────────────────────

class _ExportWorker(QThread):
    finished = Signal(str)        # success message
    error    = Signal(str)        # error message
    progress = Signal(int, int)   # (done, total)

    def __init__(self, caches: list, output_path: Path, fmt: str):
        super().__init__()
        self._caches      = caches
        self._output_path = output_path
        self._fmt         = fmt          # "gpx" | "loc" | "ggz"

    def run(self) -> None:
        try:
            from opensak.gps.garmin import generate_gpx, generate_loc, generate_ggz

            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            cb = make_progress_cb(self.progress.emit)

            if self._fmt == "gpx":
                content = generate_gpx(self._caches, self._output_path.stem, progress_cb=cb)
                self._output_path.write_text(content, encoding="utf-8")
            elif self._fmt == "loc":
                content = generate_loc(self._caches, progress_cb=cb)
                self._output_path.write_text(content, encoding="utf-8")
            elif self._fmt == "ggz":
                data = generate_ggz(self._caches, self._output_path.stem, progress_cb=cb)
                self._output_path.write_bytes(data)

            count = len([c for c in self._caches if c.latitude is not None])
            self.finished.emit(
                tr("file_export_done_msg").format(
                    count=count, path=str(self._output_path)
                )
            )
        except Exception as exc:
            import traceback
            self.error.emit(traceback.format_exc())


# ── Dialog ────────────────────────────────────────────────────────────────────

class FileExportDialog(QDialog):
    """Dialog for exporting filtered caches to GPX, LOC or GGZ format."""

    def __init__(self, caches: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("file_export_dialog_title"))
        self.setMinimumWidth(480)
        self._caches = caches
        self._worker: _ExportWorker | None = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Info label
        count = len([c for c in self._caches if c.latitude is not None])
        info = QLabel(tr("file_export_cache_count").format(count=count))
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        # Format selector
        fmt_group = QGroupBox(tr("file_export_format_label"))
        fmt_layout = QVBoxLayout(fmt_group)

        self._btn_gpx = QRadioButton("GPX  —  " + tr("file_export_fmt_gpx_desc"))
        self._btn_loc = QRadioButton("LOC  —  " + tr("file_export_fmt_loc_desc"))
        self._btn_ggz = QRadioButton("GGZ  —  " + tr("file_export_fmt_ggz_desc"))
        self._btn_gpx.setChecked(True)

        self._fmt_grp = QButtonGroup(self)
        self._fmt_grp.addButton(self._btn_gpx)
        self._fmt_grp.addButton(self._btn_loc)
        self._fmt_grp.addButton(self._btn_ggz)

        fmt_layout.addWidget(self._btn_gpx)
        fmt_layout.addWidget(self._btn_loc)
        fmt_layout.addWidget(self._btn_ggz)
        layout.addWidget(fmt_group)

        # Progress / log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        self._log.setVisible(False)
        layout.addWidget(self._log)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_export = QPushButton(tr("file_export_btn_export"))
        self._btn_export.setDefault(True)
        self._btn_export.clicked.connect(self._do_export)

        btn_close = QPushButton(tr("close"))
        btn_close.clicked.connect(self.reject)

        btn_row.addStretch()
        btn_row.addWidget(self._btn_export)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _current_fmt(self) -> str:
        if self._btn_loc.isChecked():
            return "loc"
        if self._btn_ggz.isChecked():
            return "ggz"
        return "gpx"

    def _do_export(self) -> None:
        fmt = self._current_fmt()
        ext = fmt  # gpx | loc | ggz

        filters = {
            "gpx": "GPX Files (*.gpx)",
            "loc": "LOC Files (*.loc)",
            "ggz": "GGZ Files (*.ggz)",
        }

        path_str, _ = QFileDialog.getSaveFileName(
            self,
            tr("file_export_save_dialog_title"),
            f"opensak_export.{ext}",
            filters[fmt],
        )
        if not path_str:
            return

        output_path = Path(path_str)
        if output_path.suffix.lower() != f".{ext}":
            output_path = output_path.with_suffix(f".{ext}")

        self._log.clear()
        self._log.setVisible(True)
        self._reset_progress()
        self._progress.setVisible(True)
        self._btn_export.setEnabled(False)

        self._worker = _ExportWorker(self._caches, output_path, fmt)
        self._worker.finished.connect(self._on_success)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()

    def _reset_progress(self) -> None:
        """Reset the bar to the indeterminate "running" state."""
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)

    def _on_progress(self, done: int, total: int) -> None:
        """Switch to a determinate bar showing count and percentage."""
        if total <= 0:
            return
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress.setFormat("%v / %m  (%p%)")
        self._progress.setTextVisible(True)

    def _on_success(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._btn_export.setEnabled(True)
        self._log.setPlainText("✓ " + msg)

    def _on_error(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._btn_export.setEnabled(True)
        self._log.setPlainText("✗ " + msg)
        QMessageBox.critical(self, tr("file_export_error_title"), msg)
