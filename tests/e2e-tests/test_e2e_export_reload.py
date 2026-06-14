"""tests/e2e-tests/test_e2e_export_reload.py — regression for the #207 export crash.

Table-model caches are partial and detached, so exporting them used to raise DetachedInstanceError; the workers now reload full caches before generating.
"""

import pytest

pytest.importorskip("pytestqt")


def _table_caches(window):
    # The exact (partial, detached) objects the export menu hands to a dialog.
    model = window._cache_table._model
    return [
        c
        for c in (model.cache_at(i) for i in range(window._cache_table.row_count()))
        if c is not None
    ]


def test_table_caches_are_detached_and_deferred(seeded_window):
    """Precondition: the objects the export receives are the ones that crashed —
    detached, with a deferred encoded_hints column that needs a live session."""
    from sqlalchemy.orm.exc import DetachedInstanceError

    caches = _table_caches(seeded_window)
    assert caches
    with pytest.raises(DetachedInstanceError):
        _ = caches[0].encoded_hints


def test_file_export_reloads_full_caches(seeded_window, tmp_path):
    """Exporting table caches to GPX no longer crashes, and the output includes
    the hint (deferred) and log text (noload'ed) that were absent at load time."""
    from opensak.gui.dialogs.file_export_dialog import _ExportWorker

    caches = _table_caches(seeded_window)
    out = tmp_path / "reload.gpx"

    worker = _ExportWorker(caches, out, "gpx")
    errors = []
    worker.error.connect(errors.append)
    worker.run()  # synchronous — deterministic, no thread to wait on

    assert not errors, errors
    content = out.read_text(encoding="utf-8")
    assert "Under a rock." in content      # encoded_hints (deferred) reloaded
    assert "TFTC! Great hide." in content   # log text (noload'ed) reloaded
