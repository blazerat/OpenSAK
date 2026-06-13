"""
tests/e2e-tests/conftest.py — Shared fixtures for e2e GUI tests.
"""

import pytest

pytest.importorskip("pytestqt")

from tests.data import make_fake_manager, seed_standard_caches


@pytest.fixture(autouse=True)
def _quiet_startup(monkeypatch):
    """Neutralise the delayed startup side-effects that make e2e runs flaky.

    ``MainWindow.__init__`` schedules three ``singleShot`` callbacks that fire
    seconds later — long after a fast test has set up its own state, and during
    the slow monkey test:

      * ``_initial_load``          (+500 ms) re-refreshes the table, which can
        clobber a filter the test just applied.
      * ``_check_update_background`` (+5 s)  runs a network update check (also
        stubbed offline in the top-level conftest).
      * ``_check_setup_complete``   (+7 s)  pops a modal "welcome / finish
        setup" dialog over the window under test.

    The window fixtures below populate the table explicitly via
    ``_refresh_cache_list()``, so neutralising all three makes every e2e window
    fully deterministic with no pending timers.
    """
    from opensak.gui.mainwindow import MainWindow

    monkeypatch.setattr(MainWindow, "_initial_load", lambda self: None)
    monkeypatch.setattr(MainWindow, "_check_update_background", lambda self: None)
    monkeypatch.setattr(MainWindow, "_check_setup_complete", lambda self: None)


def _make_window(qtbot, tmp_path, monkeypatch, *, name: str, seed: bool):
    """Build a shown MainWindow on a throwaway DB, optionally pre-seeded.

    Shared implementation behind :func:`seeded_window` and :func:`empty_window`.
    """
    import opensak.db.manager as mgr_module
    from opensak.db.database import init_db
    from opensak.lang import load_language

    load_language("en")

    db_path = tmp_path / f"{name}.db"
    init_db(db_path=db_path)
    if seed:
        seed_standard_caches(tmp_path)

    monkeypatch.setattr(mgr_module, "_manager", make_fake_manager(db_path, name=name))

    from opensak.gui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._refresh_cache_list()  # synchronous — table is populated on return

    try:
        yield window
    finally:
        window.close()
        mgr_module._manager = None


@pytest.fixture
def seeded_window(qtbot, tmp_path, monkeypatch):
    """MainWindow backed by a throwaway database pre-seeded with 4 test caches."""
    yield from _make_window(qtbot, tmp_path, monkeypatch, name="E2ETest", seed=True)


@pytest.fixture
def empty_window(qtbot, tmp_path, monkeypatch):
    """MainWindow backed by a fresh empty database (0 caches)."""
    yield from _make_window(qtbot, tmp_path, monkeypatch, name="E2EEmpty", seed=False)
