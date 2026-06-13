"""
tests/unit-tests/test_phase4_distance.py — Phase 4 tests.

Phase 4 vectorises the great-circle distance/bearing computation (numpy) and
adds a lat/lon bounding-box pre-narrow to DistanceFilter so distance filtering
on large databases does not haversine every row in Python.

Tests assert:
  * the batch (numpy) haversine/bearing match the scalar versions exactly
  * DistanceFilter with the SQL bounding-box returns the *same* caches as the
    pure-Python exact filter (the box is a conservative superset; matches()
    refines), including the antimeridian/pole fall-back cases
  * the (latitude, longitude) index exists
"""

import math

import pytest

from opensak.db.database import get_session, make_session
from opensak.db.models import Cache
from opensak.filters.engine import (
    _haversine_km, haversine_km_batch, apply_filters, FilterSet, DistanceFilter,
)
from opensak.gui.cache_table import _bearing_deg, _bearing_deg_batch


# ── Batch vs scalar parity ────────────────────────────────────────────────────

SAMPLE_POINTS = [
    (55.6761, 12.5683),   # Copenhagen
    (56.1629, 10.2039),   # Aarhus
    (52.5200, 13.4050),   # Berlin
    (-33.8688, 151.2093), # Sydney (southern hemisphere)
    (64.1466, -21.9426),  # Reykjavik
    (0.0, 0.0),           # null island
    (55.6761, 12.5683),   # exact same as origin → distance 0
]


@pytest.mark.parametrize("origin", [(55.6761, 12.5683), (-10.0, 170.0)])
def test_haversine_batch_matches_scalar(origin):
    lat0, lon0 = origin
    lats = [p[0] for p in SAMPLE_POINTS]
    lons = [p[1] for p in SAMPLE_POINTS]
    batch = haversine_km_batch(lat0, lon0, lats, lons)
    for i, (la, lo) in enumerate(SAMPLE_POINTS):
        assert float(batch[i]) == pytest.approx(_haversine_km(lat0, lon0, la, lo), abs=1e-6)


@pytest.mark.parametrize("origin", [(55.6761, 12.5683), (-10.0, 170.0)])
def test_bearing_batch_matches_scalar(origin):
    lat0, lon0 = origin
    lats = [p[0] for p in SAMPLE_POINTS]
    lons = [p[1] for p in SAMPLE_POINTS]
    batch = _bearing_deg_batch(lat0, lon0, lats, lons)
    for i, (la, lo) in enumerate(SAMPLE_POINTS):
        assert float(batch[i]) == pytest.approx(_bearing_deg(lat0, lon0, la, lo), abs=1e-6)


def test_haversine_batch_empty():
    assert list(haversine_km_batch(55.0, 12.0, [], [])) == []


# ── Bounding-box DistanceFilter parity ────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def seed_grid(tmp_db):
    """A grid of caches around Copenhagen + a couple of far-away ones."""
    rows = []
    n = 0
    for dlat in range(-10, 11):
        for dlon in range(-10, 11):
            n += 1
            rows.append(Cache(
                gc_code=f"GCG{n:04d}", name=f"grid {n}", cache_type="Traditional Cache",
                latitude=55.6761 + dlat * 0.05, longitude=12.5683 + dlon * 0.05,
            ))
    # Far away — must always be excluded by a Copenhagen-centred filter
    rows.append(Cache(gc_code="GCFAR1", name="Sydney", cache_type="Traditional Cache",
                      latitude=-33.8688, longitude=151.2093))
    rows.append(Cache(gc_code="GCFAR2", name="Berlin", cache_type="Traditional Cache",
                      latitude=52.52, longitude=13.405))
    s = make_session()
    for r in rows:
        s.add(r)
    s.commit()
    s.close()


def _python_only(fs):
    """Result if the filter ran purely in Python (no SQL pre-narrow)."""
    with get_session() as s:
        rows = s.query(Cache).all()
        return {c.gc_code for c in rows if fs.matches(c)}


def _via_apply_filters(fs):
    with get_session() as s:
        return {c.gc_code for c in apply_filters(s, fs)}


@pytest.mark.parametrize("max_km", [1.0, 5.0, 10.0, 25.0, 100.0])
def test_distance_filter_bbox_matches_python(max_km):
    fs = FilterSet().add(DistanceFilter(lat=55.6761, lon=12.5683, max_km=max_km))
    assert _via_apply_filters(fs) == _python_only(fs)


def test_distance_filter_with_min_km():
    fs = FilterSet().add(DistanceFilter(lat=55.6761, lon=12.5683, max_km=20.0, min_km=5.0))
    assert _via_apply_filters(fs) == _python_only(fs)


def test_distance_filter_bbox_skipped_near_antimeridian():
    # lon close to 180 → box would wrap; apply_to_query must return None so the
    # filter falls back to Python and still returns the correct set.
    f = DistanceFilter(lat=0.0, lon=179.9, max_km=50.0)
    with get_session() as s:
        assert f.apply_to_query(s.query(Cache)) is None
    fs = FilterSet().add(f)
    assert _via_apply_filters(fs) == _python_only(fs)


def test_distance_filter_bbox_skipped_for_zero_radius():
    f = DistanceFilter(lat=55.0, lon=12.0, max_km=0.0)
    with get_session() as s:
        assert f.apply_to_query(s.query(Cache)) is None


# ── Index exists ──────────────────────────────────────────────────────────────

def test_lat_lon_index_created(tmp_db):
    from sqlalchemy import text
    with get_session() as s:
        names = {
            row[0] for row in s.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='caches'"
            ))
        }
    assert "ix_caches_lat_lon" in names
