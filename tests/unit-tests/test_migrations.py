"""
tests/unit-tests/test_migrations.py — Startup migration gate (PRAGMA user_version).

The startup migration block is gated behind PRAGMA user_version so a database
already at the current schema skips the ~10 idempotent PRAGMA table_info probes
that would otherwise run on every launch. The migrations themselves are
unchanged; only the gate (skip-when-current, stamp-after-run) is exercised here.

Tests assert:
  * init_db stamps user_version to SCHEMA_VERSION
  * a current database short-circuits — no table_info probes
  * a stale database (user_version=0) re-runs the probes and is re-stamped
  * the schema migrations still produced their indexes (gate opened at least once)
"""

import pytest
from sqlalchemy import event, text

from opensak.db.database import init_db, get_engine, _run_migrations, SCHEMA_VERSION


def _capture_statements(engine):
    """Return (list, detach) capturing every SQL statement run on *engine*."""
    seen: list[str] = []

    def _listener(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _listener)
    return seen, lambda: event.remove(engine, "before_cursor_execute", _listener)


def test_user_version_stamped_after_init(tmp_path):
    init_db(db_path=tmp_path / "v.db")
    with get_engine().connect() as c:
        assert c.execute(text("PRAGMA user_version")).scalar() == SCHEMA_VERSION


def test_migrations_skipped_when_current(tmp_path):
    """A second migration pass on an up-to-date DB must not probe table_info."""
    init_db(db_path=tmp_path / "skip.db")
    engine = get_engine()

    seen, detach = _capture_statements(engine)
    try:
        _run_migrations(engine)
    finally:
        detach()

    assert not any("table_info" in s for s in seen), \
        f"gate did not short-circuit: {[s for s in seen if 'table_info' in s]}"
    # The only thing it should have read is the version gate.
    assert any("user_version" in s for s in seen)


def test_migrations_rerun_when_version_stale(tmp_path):
    """Resetting user_version=0 must re-open the gate and re-stamp afterwards."""
    init_db(db_path=tmp_path / "stale.db")
    engine = get_engine()

    with engine.connect() as c:
        c.execute(text("PRAGMA user_version = 0"))
        c.commit()

    seen, detach = _capture_statements(engine)
    try:
        _run_migrations(engine)
    finally:
        detach()

    assert any("table_info" in s for s in seen), "gate stayed shut on a stale DB"
    with engine.connect() as c:
        assert c.execute(text("PRAGMA user_version")).scalar() == SCHEMA_VERSION


def test_indexes_present_after_init(tmp_path):
    """Sanity: the gated migration block still created the filter/sort indexes."""
    init_db(db_path=tmp_path / "idx.db")
    with get_engine().connect() as c:
        names = {
            row[0] for row in c.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='caches'"
            ))
        }
    for expected in ("ix_caches_cache_type", "ix_caches_lat_lon", "ix_caches_found"):
        assert expected in names
