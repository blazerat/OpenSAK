# tests/unit-tests/test_cache_detail.py — cache detail panel helpers.

from datetime import datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("pytestqt")

from opensak.gui import cache_detail as cd
from opensak.gui.cache_detail import CacheDetailPanel
from opensak.lang import tr
from opensak.utils.types import CoordFormat, DateFormat, TEXT_SIZE_MAP, TextSize


def _fake_settings(
    fmt: DateFormat = DateFormat.DMY,
    text_size: TextSize = TextSize.MEDIUM,
    coord_format: CoordFormat = CoordFormat.DMM,
) -> SimpleNamespace:
    return SimpleNamespace(date_format=fmt, text_size=text_size, coord_format=coord_format)


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


def _fake_wp(prefix="PK", wp_type="Parking Area", name="Park here",
             lat=55.0, lon=12.0, description="", comment=""):
    return SimpleNamespace(
        prefix=prefix, wp_type=wp_type, name=name,
        latitude=lat, longitude=lon,
        description=description, comment=comment,
    )


def test_waypoints_tab_empty(monkeypatch, qapp):
    # Regression for #378: cache with no child waypoints shows the empty message.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings())
    panel = CacheDetailPanel()
    panel._render_waypoints(SimpleNamespace(waypoints=[]))
    assert tr("detail_no_waypoints") in panel._wp_browser.toPlainText()
    assert panel._tabs.tabText(3) == tr("detail_tab_waypoints")


def test_waypoints_tab_count_in_title(monkeypatch, qapp):
    # Regression for #378: tab title shows count when waypoints are present.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings())
    panel = CacheDetailPanel()
    panel._render_waypoints(SimpleNamespace(waypoints=[_fake_wp(), _fake_wp("SB", "Stages Begin", "Stage 1")]))
    assert panel._tabs.tabText(3) == tr("detail_tab_waypoints_count", count=2)


def test_waypoints_tab_renders_fields(monkeypatch, qapp):
    # Regression for #378: prefix, type, name, coords and description are shown.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings())
    panel = CacheDetailPanel()
    wp = _fake_wp(prefix="FN", wp_type="Final Location", name="The final", lat=55.1, lon=12.1, description="Dig here")
    panel._render_waypoints(SimpleNamespace(waypoints=[wp]))
    html = panel._wp_browser.toHtml()
    assert "FN" in html
    assert "Final Location" in html
    assert "The final" in html
    assert "Dig here" in html


def test_waypoints_tab_no_coords(monkeypatch, qapp):
    # Regression for #378: waypoint with missing coords shows fallback text.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings())
    panel = CacheDetailPanel()
    wp = _fake_wp(lat=None, lon=None)
    panel._render_waypoints(SimpleNamespace(waypoints=[wp]))
    assert tr("detail_wp_no_coords") in panel._wp_browser.toHtml()


def test_waypoints_tab_cleared_on_clear(monkeypatch, qapp):
    # Regression for #378: clear() resets the waypoints tab to its default state.
    monkeypatch.setattr(cd, "get_settings", lambda: _fake_settings())
    panel = CacheDetailPanel()
    panel._render_waypoints(SimpleNamespace(waypoints=[_fake_wp()]))
    assert panel._tabs.tabText(3) == tr("detail_tab_waypoints_count", count=1)
    panel.clear()
    assert panel._tabs.tabText(3) == tr("detail_tab_waypoints")
    assert panel._wp_browser.toPlainText() == ""
