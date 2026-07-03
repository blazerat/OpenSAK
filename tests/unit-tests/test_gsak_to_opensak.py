# tests/unit-tests/test_gsak_to_opensak.py — GSAK boundary converter output contract.

import json
import sqlite3
import zipfile
from pathlib import Path

from tools.boundaries import gsak_to_opensak as conv

_SQUARE = "1.0,1.0\n1.0,2.0\n2.0,2.0\n2.0,1.0\n1.0,1.0\n"


def _write_bb_db3(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE Version (Type, Country, State, Version integer);
        CREATE TABLE bb_country (File, Country, MaxLat real, MinLat real, MaxLon real, MinLon real);
        CREATE TABLE bb_state (Country, File, MaxLat real, MinLat real, MaxLon real, MinLon real, Sname);
        CREATE TABLE bb_county (Country, State, File, MaxLat real, MinLat real, MaxLon real, MinLon real, Cname);
        """
    )
    db.execute("INSERT INTO Version VALUES ('c', '', '', 1)")
    db.execute("INSERT INTO Version VALUES ('y', 'usa', 'california', 3)")
    db.execute("INSERT INTO Version VALUES ('y', 'usa', 'texas', 5)")
    db.execute("INSERT INTO bb_country VALUES ('1', 'United States', 2.0, 1.0, 2.0, 1.0)")
    db.execute(
        "INSERT INTO bb_county VALUES ('usa', 'california', '1', 2.0, 1.0, 2.0, 1.0, 'Alpha County')"
    )
    db.execute(
        "INSERT INTO bb_county VALUES ('usa', 'texas', '2', 2.0, 1.0, 2.0, 1.0, 'Beta County')"
    )
    db.commit()
    db.close()


def _write_county_zip(path: Path, file_id: str, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{file_id}.txt", f"# GsakName={name}\n{_SQUARE}")


def _write_country_zip(path: Path, file_id: str, name: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(file_id, f"# GsakName={name}\n{_SQUARE}")


def test_county_packs_are_flat_and_manifest_matches_real_versions(tmp_path: Path) -> None:
    bb_path = tmp_path / "bb.db3"
    _write_bb_db3(bb_path)
    _write_country_zip(tmp_path / "country_v1.zip", "1", "United States")
    _write_county_zip(tmp_path / "counties" / "usa" / "california_v3.zip", "1", "Alpha County")
    _write_county_zip(tmp_path / "counties" / "usa" / "texas_v5.zip", "2", "Beta County")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _run(bb_path, tmp_path, out_dir)

    counties_dir = out_dir / "counties"
    packs = sorted(p.name for p in counties_dir.iterdir())
    assert packs == ["usa_california.geojson", "usa_texas.geojson"]
    # No nested per-country subdirectory should be created.
    assert all(p.is_file() for p in counties_dir.iterdir())

    db = sqlite3.connect(out_dir / "boundaries.db")
    db.row_factory = sqlite3.Row
    rows = {r["name"]: r["pack"] for r in db.execute("SELECT name, pack FROM region_county")}
    assert rows == {"Alpha County": "usa_california.geojson", "Beta County": "usa_texas.geojson"}
    assert all("/" not in pack for pack in rows.values())

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["dataset_version"] == "1"
    assert manifest["packs"]["usa_california.geojson"]["version"] == "3"
    assert manifest["packs"]["usa_texas.geojson"]["version"] == "5"


def _run(bb_path: Path, gsak_dir: Path, out_dir: Path) -> None:
    import sys

    argv = sys.argv
    sys.argv = [
        "gsak_to_opensak.py",
        "--bb-path", str(bb_path),
        "--gsak-dir", str(gsak_dir),
        "--out-dir", str(out_dir),
    ]
    try:
        conv.main()
    finally:
        sys.argv = argv
