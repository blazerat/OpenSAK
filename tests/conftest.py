"""
tests/conftest.py — Shared fixtures for OpenSAK tests.
"""

import os

# QtWebEngine's in-process GPU thread (Chrome_InProcGpuThread) crashes under the
# test harness — SIGTRAP on macOS where the GPU context is "marked as lost", and
# the GPU path is also unavailable on the Linux CI runners. The map widget only
# needs WebEngine to load HTML, never GPU rendering, so force software rendering
# for the whole test session. Must be set before QtWebEngine initialises (i.e.
# before the first QWebEngineView is created), so it lives at conftest import
# time. setdefault() lets the CI workflow override it if it sets its own flags.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-software-rasterizer --disable-gpu-compositing",
)

import pytest
from opensak.db.database import init_db, make_session
from opensak.db.models import Cache


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    """Create a fresh SQLite DB in a temp directory for a test module."""
    db_path = tmp_path_factory.mktemp("data") / "test.db"
    init_db(db_path=db_path)
    return db_path


@pytest.fixture
def db_session(tmp_path):
    """Fresh isolated DB + bare Session for each test. Caller must commit."""
    db_path = tmp_path / "test.db"
    init_db(db_path=db_path)
    session = make_session()
    yield session
    session.close()


@pytest.fixture
def make_cache():
    """Return a factory that builds Cache instances with sensible defaults."""
    def _factory(gc_code: str = "GC12345", **kwargs) -> Cache:
        defaults = dict(
            name="Test Cache",
            cache_type="Traditional Cache",
            latitude=55.0,
            longitude=12.0,
        )
        defaults.update(kwargs)
        return Cache(gc_code=gc_code, **defaults)
    return _factory
