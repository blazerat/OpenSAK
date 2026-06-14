"""tests/unit-tests/test_corrected_coords_dialog.py — corrected-coords entry dialog."""

import pytest
from unittest.mock import MagicMock

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication, QDialog

from opensak.gui.dialogs import corrected_coords_dialog as ccd
from opensak.gui.dialogs.corrected_coords_dialog import CorrectedCoordsDialog
from opensak.utils.types import CoordFormat

_VALID = "N55 47.250 E012 25.000"


@pytest.fixture
def settings(monkeypatch):
    m = MagicMock()
    m.coord_format = CoordFormat.DMM
    monkeypatch.setattr(ccd, "get_settings", lambda: m)
    return m


class TestCorrectedCoordsDialog:
    def test_builds_with_no_coords(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        assert dlg.get_coords() == (None, None)
        assert dlg._ok_btn.isEnabled() is False

    def test_original_panel_built(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123", orig_lat=55.0, orig_lon=12.0)
        qtbot.addWidget(dlg)
        assert dlg._ok_btn.isEnabled() is False

    def test_prefilled_corrected_enables_ok(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123", corrected_lat=55.0, corrected_lon=12.0)
        qtbot.addWidget(dlg)
        lat, lon = dlg.get_coords()
        assert lat == pytest.approx(55.0, abs=1e-3)
        assert dlg._ok_btn.isEnabled() is True

    def test_valid_input_enables_ok_and_sets_coords(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._input.setText(_VALID)
        lat, lon = dlg.get_coords()
        assert lat is not None and lon is not None
        assert dlg._ok_btn.isEnabled() is True

    def test_invalid_input_shows_error(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._input.setText("garbage")
        assert dlg.get_coords() == (None, None)
        assert dlg._ok_btn.isEnabled() is False
        assert dlg._error_lbl.text() != ""

    def test_clearing_input_resets(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._input.setText(_VALID)
        dlg._input.setText("")
        assert dlg.get_coords() == (None, None)
        assert dlg._ok_btn.isEnabled() is False

    def test_accept_with_valid_coords(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._input.setText(_VALID)
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_accept_without_coords_does_nothing(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted

    def test_copy_sets_clipboard(self, qtbot, settings):
        dlg = CorrectedCoordsDialog("GC123")
        qtbot.addWidget(dlg)
        dlg._copy("hello world")
        assert QApplication.clipboard().text() == "hello world"
