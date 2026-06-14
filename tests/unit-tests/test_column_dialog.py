# tests/unit-tests/test_column_dialog.py — column chooser dialog + QSettings helpers.

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from opensak.gui.dialogs import column_dialog as cd
from opensak.gui.dialogs.column_dialog import (
    ALWAYS_VISIBLE,
    ColumnChooserDialog,
    get_all_columns,
    get_column_widths,
    get_visible_columns,
    set_column_widths,
    set_visible_columns,
)


class _FakeSettings:
    def __init__(self, store):
        self._store = store

    def value(self, key, default=None):
        return self._store.get(key, default)

    def setValue(self, key, val):
        self._store[key] = val

    def sync(self):
        pass


@pytest.fixture
def store(monkeypatch):
    data: dict = {}
    monkeypatch.setattr(cd, "QSettings", lambda *a, **k: _FakeSettings(data))
    return data


# ── module-level helpers ──────────────────────────────────────────────────────

class TestColumnHelpers:
    def test_get_all_columns_shape(self):
        cols = get_all_columns()
        assert all(len(c) == 4 for c in cols)
        assert {"gc_code", "name"} <= {c[0] for c in cols}

    def test_visible_defaults_when_unset(self, store):
        vis = get_visible_columns()
        assert "gc_code" in vis
        assert "country" not in vis  # not a default-visible column

    def test_visible_roundtrip(self, store):
        set_visible_columns(["gc_code", "name", "country"])
        assert get_visible_columns() == ["gc_code", "name", "country"]

    def test_widths_default_empty(self, store):
        assert get_column_widths() == {}

    def test_widths_roundtrip(self, store):
        set_column_widths({"gc_code": 80})
        assert get_column_widths() == {"gc_code": 80}

    def test_widths_bad_json_returns_empty(self, store):
        store["columns/widths"] = "{ not json"
        assert get_column_widths() == {}


# ── ColumnChooserDialog ───────────────────────────────────────────────────────

class TestColumnChooserDialog:
    def test_select_all_checks_everything(self, qtbot, store):
        dlg = ColumnChooserDialog()
        qtbot.addWidget(dlg)
        dlg._select_all()
        states = [dlg._list.item(i).checkState() for i in range(dlg._list.count())]
        assert all(s == Qt.CheckState.Checked for s in states)

    def test_select_default_unchecks_non_default(self, qtbot, store):
        dlg = ColumnChooserDialog()
        qtbot.addWidget(dlg)
        dlg._select_all()
        dlg._select_default()
        for i in range(dlg._list.count()):
            item = dlg._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == "country":
                assert item.checkState() == Qt.CheckState.Unchecked

    def test_save_persists_checked_and_always_visible(self, qtbot, store):
        dlg = ColumnChooserDialog()
        qtbot.addWidget(dlg)
        dlg._select_default()
        dlg._save_and_accept()
        saved = get_visible_columns()
        assert "gc_code" in saved
        assert "name" in saved

    def test_always_visible_columns_not_checkable(self, qtbot, store):
        dlg = ColumnChooserDialog()
        qtbot.addWidget(dlg)
        for i in range(dlg._list.count()):
            item = dlg._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in ALWAYS_VISIBLE:
                assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
