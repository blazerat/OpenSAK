"""
tests/unit-tests/test_phase5_importer.py — Phase 5 importer throughput tests.

Phase 5 speeds up the importer without changing what it writes:
  * a single ``{gc_code: id}`` preload replaces the per-cache ``filter_by`` SELECT
    (a brand-new cache is now detected by a dict miss, not a round-trip)
  * child deletes use ``synchronize_session=False`` and the extra/companion
    waypoint helpers delete in one batched ``IN (...)`` instead of one per suffix
  * SQLite durability is relaxed (``synchronous=NORMAL``) for the import and
    restored afterwards

These tests pin the behaviour that must NOT change (re-import idempotency,
in-file duplicate handling, companion-waypoint linking) and assert the two
mechanisms the speed-up relies on (no per-cache gc_code lookup; the durability
PRAGMA is set during import and restored after).
"""

import pytest
from pathlib import Path

from sqlalchemy import event, text

from opensak.db.database import init_db, get_session, get_engine, make_session
from opensak.db.models import Cache, Log, Attribute, Waypoint, Trackable
from opensak.importer import (
    import_gpx,
    _enter_bulk_import_pragmas,
    _exit_bulk_import_pragmas,
)

from tests.data import SAMPLE_GPX, SAMPLE_WPTS_GPX, write_gpx


@pytest.fixture
def gpx_file(tmp_path) -> Path:
    return write_gpx(tmp_path, "test.gpx", SAMPLE_GPX)


def _counts(session) -> dict:
    return {
        "caches":     session.query(Cache).count(),
        "logs":       session.query(Log).count(),
        "attributes": session.query(Attribute).count(),
        "waypoints":  session.query(Waypoint).count(),
        "trackables": session.query(Trackable).count(),
    }


# ── Re-import idempotency ─────────────────────────────────────────────────────

def test_reimport_is_idempotent(tmp_path, gpx_file):
    """Importing the same GPX twice must leave the DB byte-for-byte equivalent."""
    init_db(db_path=tmp_path / "idem.db")

    r1 = import_gpx(gpx_file)
    assert r1.errors == []
    with get_session() as s:
        first = _counts(s)

    r2 = import_gpx(gpx_file)
    assert r2.errors == []
    with get_session() as s:
        second = _counts(s)

    assert first == second, f"DB changed on re-import: {first} -> {second}"
    # No duplicate caches, and child rows were rebuilt, not accumulated.
    assert second["caches"] == 2
    with get_session() as s:
        cache = s.query(Cache).filter_by(gc_code="GC12345").one()
        assert len(cache.logs) == 2
        assert len(cache.attributes) == 2


def test_reimport_with_companion_wpts_idempotent(tmp_path):
    """Companion-waypoint linking must also be idempotent across re-imports."""
    init_db(db_path=tmp_path / "idem_wpts.db")
    gpx = write_gpx(tmp_path, "c.gpx", SAMPLE_GPX)
    wpts = write_gpx(tmp_path, "c-wpts.gpx", SAMPLE_WPTS_GPX)

    import_gpx(gpx, wpts_path=wpts)
    import_gpx(gpx, wpts_path=wpts)

    with get_session() as s:
        cache = s.query(Cache).filter_by(gc_code="GC12345").one()
        # Exactly one PK waypoint — not duplicated on the second import.
        assert sum(1 for w in cache.waypoints if w.prefix == "PK") == 1
        assert s.query(Waypoint).count() == 1


# ── In-file duplicate handling (preload map stays correct) ────────────────────

def test_duplicate_gc_in_same_file_updates(tmp_path):
    """Two <wpt> with the same GC code in one file → one row, no UNIQUE error."""
    init_db(db_path=tmp_path / "dup.db")
    # Make both caches share GC12345 (second carries the GC99999 payload).
    dup_gpx = SAMPLE_GPX.replace("GC99999", "GC12345")
    f = write_gpx(tmp_path, "dup.gpx", dup_gpx)

    result = import_gpx(f)
    assert result.errors == []
    with get_session() as s:
        assert s.query(Cache).filter_by(gc_code="GC12345").count() == 1


# ── N+1 elimination: no per-cache gc_code SELECT on a fresh import ────────────

def test_fresh_import_has_no_per_cache_gc_lookup(tmp_path):
    """A fresh import must not issue 'WHERE caches.gc_code = ?' per cache."""
    init_db(db_path=tmp_path / "fresh.db")
    f = write_gpx(tmp_path, "fresh.gpx", SAMPLE_GPX)

    seen: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        import_gpx(f)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    per_cache = [s for s in seen if "WHERE caches.gc_code" in s]
    assert per_cache == [], f"unexpected per-cache gc_code lookups: {per_cache}"
    # The single preload scan should be present instead.
    assert any("FROM caches" in s and "gc_code" in s and "WHERE" not in s for s in seen)


# ── Durability PRAGMA: set during import, restored after ──────────────────────

def test_bulk_import_pragmas_set_and_restore(tmp_path):
    init_db(db_path=tmp_path / "pragma.db")
    s = make_session()
    try:
        assert s.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL (default)
        _enter_bulk_import_pragmas(s)
        assert s.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL
        assert s.execute(text("PRAGMA cache_size")).scalar() == -65536
        _exit_bulk_import_pragmas(s)
        assert s.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL again
        assert s.execute(text("PRAGMA cache_size")).scalar() == -2000
    finally:
        s.close()


def test_synchronous_restored_after_import(tmp_path, gpx_file):
    """After import, normal operations must run at full durability again."""
    init_db(db_path=tmp_path / "restore.db")
    import_gpx(gpx_file)
    with get_session() as s:
        assert s.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL


# ── Batch failure isolation (fast path falls back to per-cache) ───────────────

def _cache_block(gc: str, gs_id: int, log_id: str) -> str:
    return (
        f'<wpt lat="55.{gs_id}" lon="12.{gs_id}"><n>{gc}</n>'
        f'<type>Geocache|Traditional Cache</type>'
        f'<groundspeak:cache id="{gs_id}" archived="False" available="True" '
        f'xmlns:groundspeak="http://www.groundspeak.com/cache/1/0/1">'
        f'<groundspeak:name>{gc}</groundspeak:name>'
        f'<groundspeak:type>Traditional Cache</groundspeak:type>'
        f'<groundspeak:logs><groundspeak:log id="{log_id}">'
        f'<groundspeak:date>2025-01-0{gs_id}T00:00:00Z</groundspeak:date>'
        f'<groundspeak:type>Found it</groundspeak:type>'
        f'<groundspeak:finder id="{gs_id}">F{gs_id}</groundspeak:finder>'
        f'<groundspeak:text encoded="False">log</groundspeak:text>'
        f'</groundspeak:log></groundspeak:logs></groundspeak:cache></wpt>'
    )


def test_batch_failure_isolates_only_bad_cache(tmp_path):
    """Two caches in one batch share a log_id → only the colliding one is skipped.

    This exercises the fast-path → per-cache fallback: the batch savepoint fails
    on the UNIQUE(log_id) violation, the batch is replayed cache-by-cache, and
    the first cache survives while only the second is skipped.
    """
    init_db(db_path=tmp_path / "iso.db")
    gpx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<gpx version="1.0" creator="t" xmlns="http://www.topografix.com/GPX/1/0">'
        + _cache_block("GCAAA01", 1, "DUPLICATE")
        + _cache_block("GCAAA02", 2, "DUPLICATE")
        + '</gpx>'
    )
    f = write_gpx(tmp_path, "iso.gpx", gpx)

    result = import_gpx(f)

    assert result.created == 1
    assert result.skipped == 1
    assert len(result.errors) == 1
    with get_session() as s:
        codes = {c.gc_code for c in s.query(Cache).all()}
    assert codes == {"GCAAA01"}
