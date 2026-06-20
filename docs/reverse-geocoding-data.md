# Reverse-geocoding boundary data (`data/`)

The offline boundary engine (`src/opensak/geo/`, issue #60) reads its dataset
from a **local `data/` folder at the repo root**. That folder is a *dev-only
stand-in*: it is **git-ignored** (see `.gitignore`) and exists only until the
real dataset is published to the **`AgreeDK/OpenSAK-Data`** repository and
seeded into the per-user app-data directory. The switch-over is described in
[`plans/reverse-geocoding-data-migration.md`](../plans/reverse-geocoding-data-migration.md).

Until then, drop the files below into `data/` by hand to exercise the engine.

## Where the engine looks

`geo.store.default_data_dir()` resolves, in order:

1. `$OPENSAK_BOUNDARIES_DIR` if set (used by the tests and handy for pointing at
   a throwaway dataset);
2. otherwise `<repo-root>/data`.

So `OPENSAK_BOUNDARIES_DIR=/some/path python …` overrides it without touching
the tree.

## Expected layout

`data/` mirrors the future `<app-data>/opensak/boundaries/` layout from the
[architecture doc](../architecture/reverse-geocoding.md#53-on-disk-layout-and-caching):

```
data/
├── boundaries.db        # SQLite: per-layer R-Trees + region metadata
├── manifest.json        # dataset + per-pack versions (used from Phase 2 on)
├── countries/
│   └── world.geojson    # baseline — one country FeatureCollection
├── states/
│   └── *.geojson        # baseline
└── counties/
    └── <cc>.geojson     # one FeatureCollection per country (e.g. prt.geojson)
```

## `boundaries.db` schema

One R-Tree plus one metadata table **per layer** (`country`, `state`, `county`),
joined by `id`, exactly as in [§5.2 of the architecture](../architecture/reverse-geocoding.md#52-the-bounding-box-database):

```sql
CREATE VIRTUAL TABLE rtree_<layer> USING rtree(id, min_lat, max_lat, min_lon, max_lon);

CREATE TABLE region_<layer> (
    id            INTEGER PRIMARY KEY,  -- == matching R-Tree id
    name          TEXT NOT NULL,        -- display value ('Lisboa')
    parent        TEXT,                 -- 'PT', 'US/TX' — links county→state→country
    pack          TEXT NOT NULL,        -- GeoJSON file under <layer-dir>/
    feature_index INTEGER NOT NULL,     -- which feature inside that pack
    poly_version  INTEGER NOT NULL,
    is_bundled    INTEGER NOT NULL      -- 1 baseline, 0 on-demand
);

CREATE TABLE file_version (layer TEXT, country TEXT, state TEXT, version INTEGER);
```

The engine resolves a point by: R-Tree query (`candidates`) → `region_<layer>`
row (`region`) → lazily load `<data-dir>/<layer-dir>/<pack>` and take
`features[feature_index].geometry` (`geometry`). The `<layer-dir>` is the plural
form: `country→countries`, `state→states`, `county→counties`.

## GeoJSON packs

One `FeatureCollection` per country, each feature carrying a standard `bbox`
member and `name` / `parent` / `version` / `source` / `licence` properties
([§5.1](../architecture/reverse-geocoding.md#51-polygon-files)):

```jsonc
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "layer": "county", "name": "Lisboa", "parent": "PT",
                      "version": 1, "source": "osm", "licence": "ODbL" },
      "bbox": [-9.5, 38.6, -9.0, 38.9],
      "geometry": { "type": "MultiPolygon", "coordinates": [ /* … */ ] }
    }
  ]
}
```

The `feature_index` in `region_<layer>` must match the feature's position in
this array. GeoJSON coordinates are `[lon, lat]`; the first ring is the outer
boundary, any further rings are holes.

## A minimal, runnable reference

[`tests/unit-tests/test_geo.py`](../tests/unit-tests/test_geo.py) builds a tiny
but complete `data/` directory (three counties, one state, one country) in a
temp dir via `_build_boundaries()`. It is the authoritative, executable example
of this contract — copy its output into `data/` for a working hand-made dataset.
