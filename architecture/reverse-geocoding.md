# Architecture — Offline Reverse Geocoding

OpenSAK assigns a **country**, **state/region** and **county** to every cache by
reverse geocoding its coordinates against a local, polygon-accurate boundary
dataset. The whole operation runs **offline**, on a background thread, with no
network calls on the hot path and no per-request rate limits.

This document describes the design of that subsystem — the *boundary engine*.

---

## Contents

- [1. Problem](#1-problem)
- [2. Concept](#2-concept)
- [3. Benefits](#3-benefits)
- [4. Design decisions](#4-design-decisions)
- [5. Boundary data model](#5-boundary-data-model)
- [6. System overview](#6-system-overview)
  - [6.1 The two-stage query](#61-the-two-stage-query)
  - [6.2 Build-time data pipeline](#62-build-time-data-pipeline)
  - [6.3 Distribution and updates](#63-distribution-and-updates)
- [7. Database schema](#7-database-schema)
- [8. Dependencies](#8-dependencies)
- [9. Module layout and integration](#9-module-layout-and-integration)
- [10. Performance](#10-performance)
- [11. Accuracy and edge cases](#11-accuracy-and-edge-cases)
- [12. Roadmap](#12-roadmap)
- [13. Risks](#13-risks)
- [Appendix A — Glossary](#appendix-a--glossary)

---

## 1. Problem

Geocachers need reliable **country / state (region) / county** values on every
cache, for three concrete reasons:

1. **County / region challenges.** Many caches qualify a finder for a
   "find a cache in every county"-style challenge. Going to the wrong county is
   expensive — literally, long drives — and frustrating.
2. **Filtering and trip planning.** "Show me caches in this county" only works
   when the field is populated and correct.
3. **Parity with other tools.** Users cross-check OpenSAK against GSAK,
   Project-GC and Cachetur. When the answer disagrees, OpenSAK gets the support
   ticket.

The data is **not** reliably available from the source files:

- Imported GPX / Pocket Query files generally fill `country` and sometimes
  `state`, but **county is almost always empty**.
- A cache's real-world location can differ from its *posted* coordinates —
  multi-caches and mystery/puzzle finals can sit tens of miles away. The
  territory may need computing from **corrected** coordinates.
- Boundaries change over time (county splits, `Turkey → Türkiye`,
  `Czech Republic → Czechia`). Static values go stale.

Reverse geocoding is fundamentally a **point-in-region** query: given a point,
find which administrative polygons contain it. The challenge is doing that
**accurately** (correct at and near borders) and **fast** (tens of thousands of
caches at once), entirely offline.

---

## 2. Concept

The naive solution — test the point against every polygon — is `O(regions ×
vertices)` per cache and does not scale.

The boundary engine uses a **two-stage lookup** built on a spatial index (see
[SQLite R-Tree](https://sqlite.org/rtree.html)):

1. **Stage 1 — bounding-box filter (R-Tree).** Every region is reduced to its
   min/max latitude and longitude — an axis-aligned bounding box. These boxes
   live in a SQLite **R-Tree** index. Querying it with a point returns only the
   handful of regions whose box *contains* the point. This is `O(log n)` and
   extremely fast.
2. **Stage 2 — point-in-polygon (exact).** In the common case the point lands in
   exactly one box → done, with no geometry maths. Only when boxes **overlap**
   (very common for counties, and near any border) does the engine run the
   precise point-in-polygon test, and only on the 2–3 candidates Stage 1
   returned.

This keeps the expensive geometry off the hot path. Because a county polygon
records its parent state and country, a single county hit fills all three fields
at once.

---

## 3. Benefits

- **Instant and offline.** A 10k+ cache database resolves locally in seconds.
  No network on the hot path, so it works on a plane, in the field, anywhere.
- **No rate limits, no bans.** Nothing is throttled or quota'd — the engine is
  pure local computation.
- **Polygon-accurate.** Results are correct at and near borders, not snapped to
  the nearest town. This is what challenge caching requires.
- **Auditable provenance.** Every value records where it came from (imported vs
  computed), which coordinates produced it (posted vs corrected), when, and
  against which boundary dataset version.
- **Both coordinate bases.** Posted coordinates by default (checker
  compatibility); corrected coordinates on demand for physical planning.
- **Controlled footprint.** A small baseline ships with the app; detailed
  county data downloads only when needed.
- **Live-updatable data.** Boundaries refresh independently of app releases via
  a versioned manifest.
- **Tool parity.** Built on the same public-domain boundary dataset the wider
  community already uses, so results line up with established tools.
- **Extensible.** The same engine serves any boundary *layer* — custom polygons
  (Delorme, Ordnance Survey, challenge regions) need only data, not code.

---

## 4. Design decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | **Boundary data source** | Public-domain polygon files (community/GSAK lineage), **normalised** to UTF-8 + standard GeoJSON, from which OpenSAK regenerates its own R-Tree database. | Community parity for support; crowd-sourced coverage; clean diacritics (`Türkiye`) and refreshable stale polygons. |
| D2 | **Result storage** | `Cache.country/state/county` hold the single result set; **provenance metadata** (source, coordinate basis, timestamp, dataset version) sits alongside. | Re-runnable and auditable without doubling every column. |
| D3 | **Distribution** | Ship a small **baseline** dataset (country + state); download **county packs on demand** with a checkable version number. | Controls install/DB footprint; updates boundaries without an app release. |
| D4 | **Granularity** | A **generic layered polygon engine** — country/state/county today, extensible to custom layers. | One engine for every layer; no rewrite to add custom polygons. |

Recorded alternatives:

- *Wholesale build from Natural Earth / GADM / OSM only* — clean data, but
  county coverage is hard and results diverge from established tools, generating
  support load. These sources are used to **refresh** individual polygons under
  D1, not as the wholesale base.
- *Separate `corrected_*` columns* — instead, D2's `location_basis` records
  which coordinates produced the stored value. Storing both bases at once can be
  revisited if filtering demand appears.
- *Bundle every polygon* — simplest, but bloats the install; rejected for D3.

---

## 5. Boundary data model

Two artefacts, in open formats:

### 5.1 Polygon files (the geometry)

One file per region, standard **GeoJSON** (`Feature`), UTF-8, with normalised
names. A region can be a `MultiPolygon` (islands) and may contain holes
(enclaves) — GeoJSON ring winding handles both.

```jsonc
// counties/us-tx-travis.geojson
{
  "type": "Feature",
  "properties": {
    "layer": "county",
    "name": "Travis",
    "parent": "US/TX",          // state/country this nests under
    "version": 7,               // bumped when the polygon is corrected
    "source": "community|osm|user"
  },
  "geometry": { "type": "MultiPolygon", "coordinates": [ /* ... */ ] }
}
```

### 5.2 The bounding-box database (`boundaries.db`)

A SQLite file generated **once** from all polygon files. It holds the R-Tree
plus an auxiliary metadata table, and contains **no information not derivable
from the polygons**, so it inherits their public-domain status.

```sql
-- Stage 1: R-Tree of axis-aligned bounding boxes (SQLite built-in module)
CREATE VIRTUAL TABLE region_bbox USING rtree(
    id,                 -- INTEGER primary key
    min_lat, max_lat,
    min_lon, max_lon
);

-- Auxiliary metadata, joined by id
CREATE TABLE region_meta (
    id            INTEGER PRIMARY KEY,
    layer         TEXT NOT NULL,   -- 'country' | 'state' | 'county' | <custom>
    name          TEXT NOT NULL,   -- UTF-8, normalised ('Türkiye')
    parent        TEXT,            -- e.g. 'US/TX'
    polygon_file  TEXT NOT NULL,   -- relative path to the GeoJSON
    poly_version  INTEGER NOT NULL,
    is_bundled    INTEGER NOT NULL -- 1 = in baseline install, 0 = on-demand pack
);
```

> **Why SQLite's own R-Tree** rather than an external index package: it is a
> compile-time-standard SQLite module (no extra native dependency to ship on
> Windows/macOS/Linux), it persists to disk for free, and it keeps the index
> next to the data. Point-in-polygon (Stage 2) is the only piece needing a
> geometry library — see [§8](#8-dependencies).

### 5.3 On-disk layout

Under the platform app-data directory (resolved by `config.get_app_data_dir()`):

```
<app-data>/opensak/
├── Default.db                 # the cache database
└── boundaries/
    ├── boundaries.db          # generated R-Tree + metadata (baseline)
    ├── manifest.json          # dataset + per-pack version numbers
    ├── countries/             # baseline, bundled with the install
    │   └── *.geojson
    ├── states/                # baseline, bundled with the install
    │   └── *.geojson
    └── counties/              # downloaded on demand (D3)
        └── *.geojson
```

---

## 6. System overview

```mermaid
flowchart TD
    subgraph UI["GUI thread"]
        DLG["Update Location dialog\n(scope: all / missing / this cache / filter)\n(coords: posted | corrected)"]
        IMP["GPX/PQ import\n(auto-fill on import)"]
    end

    subgraph WORKER["QThread — reverse-geocode worker"]
        BATCH["batch resolve(coords[])"]
    end

    subgraph ENGINE["geo.boundaries.TerritoryResolver"]
        S1["Stage 1: R-Tree bbox query\n(boundaries.db)"]
        S2["Stage 2: point-in-polygon\n(only on overlaps)"]
        POLY["Polygon cache\n(lazy-loaded GeoJSON)"]
    end

    subgraph STORE["geo.store + geo.packs"]
        BB[("boundaries.db")]
        GJ[["*.geojson packs"]]
        DL["on-demand pack download\n+ version check (D3)"]
    end

    DB[("Cache DB\ncountry/state/county + metadata")]

    DLG --> WORKER
    IMP --> WORKER
    BATCH --> S1
    S1 -->|1 hit| RESULT["GeoLocation"]
    S1 -->|>1 hit| S2
    S2 --> POLY
    POLY -.miss.-> DL
    S2 --> RESULT
    S1 --- BB
    POLY --- GJ
    DL --> GJ
    RESULT -->|signal| DB
```

### 6.1 The two-stage query

```
            point (lat, lon)
                  │
                  ▼
   ┌──────────────────────────────┐
   │ Stage 1  R-Tree bbox SELECT   │   ~O(log n), microseconds
   │ WHERE min_lat<=? AND max_lat  │
   │   >=? AND min_lon<=? ...       │
   └──────────────┬────────────────┘
                  │ candidate region ids
        ┌─────────┴──────────┐
        │                    │
   exactly 1 hit        2+ hits (overlap / border)
        │                    │
        ▼                    ▼
     DONE          ┌────────────────────────┐
   (no geometry)   │ Stage 2  point-in-poly  │  only on 2–3 candidates
                   │ load GeoJSON, ray-cast  │
                   │ (holes respected)       │
                   └───────────┬─────────────┘
                               ▼
                        winning region
```

The lookup runs per layer; a county hit also yields its state and country
through the polygon's `parent`, so one query can fill all three fields.

### 6.2 Build-time data pipeline

A maintainer-run pipeline lives under `tools/` (kept out of the runtime package
and excluded from release bundles). It turns raw public-domain polygons into
shippable artefacts:

```mermaid
flowchart LR
    A["raw polygon files\n(mixed encodings/formats)"] --> B["normalise\nUTF-8 names, fix diacritics,\nconvert to GeoJSON"]
    OSM["OSM / Natural Earth / GADM\n(refresh stale polygons)"] --> B
    B --> C["validate geometry\n(closed rings, winding, holes)"]
    C --> D["compute bbox per region"]
    D --> E["generate boundaries.db\n(R-Tree + meta)"]
    C --> F["split into baseline + county packs"]
    E --> G["manifest.json\n(versions)"]
    F --> G
```

`boundaries.db` is derived purely by extracting the min/max latitude and
longitude of each polygon — a quick, one-off process repeated whenever the
dataset changes.

### 6.3 Distribution and updates

- **Baseline** (`countries/`, `states/`, `boundaries.db`) ships as package data
  in the install, so country/state resolution works offline immediately.
- **County packs** download on demand: when a county lookup needs a polygon
  listed in `region_meta` but absent on disk, `geo.packs` fetches that pack from
  a versioned host (release assets / `opensak.com`).
- **`manifest.json`** carries a dataset version and per-pack versions. On launch
  (or on user request) OpenSAK compares against the remote manifest and offers
  to refresh changed packs, so boundary data — including `boundaries.db` —
  updates independently of app releases.

---

## 7. Database schema

The `Cache` model carries the three result fields plus provenance metadata:

```python
# Territory result (one set per cache)
country: Mapped[Optional[str]] = mapped_column(String(64))
state:   Mapped[Optional[str]] = mapped_column(String(64))
county:  Mapped[Optional[str]] = mapped_column(String(64))

# Provenance (D2)
location_source:  Mapped[Optional[str]] = mapped_column(String(16))   # 'groundspeak' | 'computed'
location_basis:   Mapped[Optional[str]] = mapped_column(String(16))   # 'posted' | 'corrected'
location_updated: Mapped[Optional[datetime]] = mapped_column(DateTime)
location_dataset: Mapped[Optional[str]] = mapped_column(String(32))   # boundary dataset version used
```

Corrected coordinates are read from the one-to-one `UserNote`
(`corrected_lat`, `corrected_lon`, `is_corrected`).

Schema changes are versioned through `PRAGMA user_version` (see
`db/database.py`): the engine bumps `SCHEMA_VERSION` and adds the provenance
columns idempotently, so existing databases upgrade in place with the metadata
defaulting to "unknown / imported".

The provenance fields let a user tell, per cache, whether a value came from the
import source, from posted coordinates, or from corrected coordinates — and
whether it predates a boundary refresh.

---

## 8. Dependencies

| Need | Choice | Notes |
|------|--------|-------|
| R-Tree (Stage 1) | **SQLite built-in `rtree`** | No new dependency; standard in CPython's bundled SQLite. |
| Point-in-polygon (Stage 2) | **`shapely`** | C-backed (GEOS), correct with holes/multipolygons, cross-platform wheels. A pure-Python ray-casting fallback stays available for a zero-native-dependency build, at some speed/robustness cost. |
| GeoJSON parsing | stdlib `json` | No `geojson`/`fiona`/`geopandas` needed. |
| Country code → name | `pycountry` | Normalising ISO codes to display names in the pipeline. |

---

## 9. Module layout and integration

The engine is a self-contained `geo` subpackage; the build pipeline is separate
and not packaged.

```
src/opensak/geo/
├── __init__.py
├── boundaries.py     # TerritoryResolver: two-stage lookup, returns GeoLocation
├── store.py          # locate/open boundaries.db, resolve polygon paths, lazy polygon cache
└── packs.py          # on-demand county-pack download + manifest/version check

tools/boundaries/     # build-time only, excluded from packaging
├── normalise.py      # raw polygons -> clean UTF-8 GeoJSON
├── build_bbdb.py     # GeoJSON -> boundaries.db (R-Tree + meta)
└── pack.py           # split into baseline + packs, emit manifest.json
```

`TerritoryResolver` returns a `GeoLocation(country, state, county)` value.

### GUI integration

The feature follows the project's UI conventions:

- An **Update Location** dialog drives it, reachable from the Waypoint menu and
  from the cache-table right-click menu. It offers scope (all caches / only
  missing / this cache / current filter) and a coordinate-basis choice (posted
  vs corrected, **defaulting to posted** for checker compatibility).
- Resolution runs in a **`QThread`** worker that streams progress and results
  back via Qt signals — the main thread never blocks (a 10k+ batch is heavy).
- The same worker runs automatically after a GPX/PQ import to fill missing
  territory data.
- All user-visible strings go through `tr()` with keys present in every
  `lang/*.py` module.

---

## 10. Performance

| Stage | Cost | Notes |
|-------|------|-------|
| Stage 1 (R-Tree) | ~`O(log n)` per point | Batched; tens of thousands of points in well under a second. |
| Stage 2 (polygon) | only on bbox overlaps | Typically 2–3 candidate polygons; skipped entirely for interior points. |
| Polygon I/O | lazy + cached | Each region's GeoJSON loads once and is reused across the batch — a Pocket Query clusters geographically, so cache hit rates are high. |

The work stays on the `QThread` with progress signals; a 10k+ batch completes in
seconds.

---

## 11. Accuracy and edge cases

- **Borders.** Stage 2 resolves overlapping boxes exactly. The residual risk is
  an *approximate polygon* itself — mitigated by D1's refresh pipeline and the
  user-override path on the roadmap.
- **Missing polygon.** Box hit but pack not downloaded → fetch on demand (D3);
  if offline, return the coarser layer already available (e.g. state without
  county) and flag it, never a wrong guess.
- **No box hit.** A point over open water or an unmapped area leaves the field
  empty rather than snapping to the nearest land.
- **Diacritics / renames.** Fixed at normalisation time (D1): UTF-8, `Türkiye`,
  `Czechia`, etc. `location_dataset` records the dataset version used, so
  renames stay explainable after the fact.
- **Posted vs corrected.** `location_basis` records the choice per cache;
  re-running with the other basis updates both the value and the metadata.

---

## 12. Roadmap

- **Locking and overrides.** A locked field is never overwritten by re-runs or
  import. Builds on the planned custom-fields system.
- **Macro hook.** A macro can recompute territories and stash the previous value
  in a custom field, respecting locks.
- **Custom layers.** D4's generic engine already accepts new `layer` values —
  Delorme, Ordnance Survey, challenge regions — needing only polygon packs.
- **Crowd-sourced polygon editing.** A web polygon editor could feed corrections
  back into the dataset.

---

## 13. Risks

| Risk | Mitigation |
|------|------------|
| `shapely`/GEOS native wheels across OSes | Verified in the CI matrix (3.11/3.12, Linux/macOS/Windows); pure-Python ray-cast fallback available. |
| County polygon footprint | D3 on-demand packs; ship only baseline. |
| Stale / approximate polygons | D1 refresh pipeline + `location_dataset` provenance + future overrides. |
| Disagreement with other tools | Expected when a tool applies different boundaries or a different coordinate basis. The posted/corrected toggle and `location_basis` make disagreements explainable, not silent. |
| Boundary-data licensing | Polygons are public-domain; `boundaries.db` is derived (no new information); refreshes drawn from open sources with compatible terms. |

---

## Appendix A — Glossary

- **Reverse geocoding** — turning `(lat, lon)` into place names.
- **Point-in-polygon** — geometric test of whether a point lies inside a polygon
  (ray casting / winding number).
- **R-Tree** — a tree index for rectangles; answers "which boxes contain or
  overlap this point/box?" quickly. SQLite ships one.
- **Bounding box** — the smallest axis-aligned rectangle enclosing a region; the
  Stage-1 approximation.
- **Posted vs corrected coordinates** — published listing coordinates vs the
  user's solved/real coordinates (stored on `UserNote`).
- **Layer** — a category of boundary (country / state / county / custom).
