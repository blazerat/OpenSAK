# tests/unit-tests/test_cache_detail.py — cache detail panel helpers.

from datetime import datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("pytestqt")

from opensak.gui import cache_detail as cd
from opensak.gui.cache_detail import CacheDetailPanel
from opensak.utils.types import DateFormat, TEXT_SIZE_MAP, TextSize


def _fake_settings(fmt: DateFormat = DateFormat.DMY, text_size: TextSize = TextSize.MEDIUM) -> SimpleNamespace:
    return SimpleNamespace(date_format=fmt, text_size=text_size)


@pytest.mark.parametrize("fmt, expected", [
    (DateFormat.DMY, "25.12.2024"),
    (DateFormat.MDY, "12/25/2024"),
    (DateFormat.YMD, "2024-12-25"),
])
def test_format_date_respects_settings(monkeypatch, qapp, fmt, expected):
    # Regression for #322: dates in the detail panel were hardcoded to DMY.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings(fmt))
    result = cd._format_date(datetime(2024, 12, 25))
    assert result == expected


def test_refresh_sizes_updates_title_font(monkeypatch, qapp):
    # Regression for #371: text size change in Settings had no effect until a
    # new cache was selected because _apply_ui_sizes() was never called.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings(text_size=TextSize.SMALL))
    panel = CacheDetailPanel()
    panel.refresh_sizes()
    assert panel._title.font().pointSize() == TEXT_SIZE_MAP[TextSize.SMALL]["label"]

    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings(text_size=TextSize.LARGE))
    panel.refresh_sizes()
    assert panel._title.font().pointSize() == TEXT_SIZE_MAP[TextSize.LARGE]["label"]


def test_decode_no_hint_shows_no_hint_label(qapp):
    # Regression for #324: decoding a cache with no hint showed an empty text
    # browser instead of keeping the "(no hint)" feedback visible.
    panel = CacheDetailPanel()
    panel._hint_plain = ""
    panel._hint_cipher = ""
    panel._hint_decoded = False

    panel._toggle_hint_decode()  # decode
    assert panel._hint_browser.toPlainText() != ""

    panel._toggle_hint_decode()  # encode back
    assert panel._hint_browser.toPlainText() != ""
