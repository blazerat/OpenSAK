# Development Plan — Offline Reverse Geocoding (County / State / Country)

Status: Proposed
Relates to: GitHub issue #60 · design in [`architecture/reverse-geocoding.md`](../architecture/reverse-geocoding.md)
Scope: full implementation of the offline boundary engine — data pipeline, runtime engine, on-demand packs, schema, GUI, packaging/CI.

This plan turns the architecture document into shippable work. It is ordered **bottom-up**: the data has to exist before the engine can resolve, the engine before the GUI, the GUI before the old code can be retired. Each phase is independently testable and ships on its own branch.

## How this ships

- **One branch per phase**, named `60-phase-N-<desc>` (e.g. `60-phase-1-engine`), off the synced `beta`.
- **PRs target `beta`** (per issue #257), not `main`.
- **Commit every logical step**, Conventional Commits, no co-author trailer.
- New user-visible strings go through `tr()` with keys added to **every** `lang/*.py`.
- Long work stays on a `QThread`; the main thread never blocks.

## Prerequisites

- [ ] Receive the full polygon-file set from Mike (*Lignumaqua*) — Phase 0 cannot start without the source data. The sample `bb.db3` + `Denmark1.txt` only prove the format.
- [ ] Create the data repository **`AgreeDK/OpenSAK-Data`** (public) with its own `LICENSE` + attribution file (the polygons are ODbL, not public domain).

## Out of scope (follow-ups)

- Drawing boundary outlines on the Leaflet map (the GeoJSON makes this cheap later).
- Value **locking** and the macro hook — depend on the future custom-fields system.
- Maps and altimetry datasets — separate problems, separate plans (the `OpenSAK-Data` repo is built to host them later).

---

## Phase 0 — Data pipeline and the `OpenSAK-Data` repo

**Goal:** a reproducible pipeline that turns raw polygon files into the artefacts the app consumes: a baseline, per-country county packs, the bounding-box index, and a version manifest — all published as GitHub Release assets.

**Tasks**
- [ ] `tools/boundaries/normalise.py` — read native GSAK text polygons, re-encode to UTF-8, fix diacritics/renames (`Türkiye`, `Czechia`), consistent keys.
- [ ] `tools/boundaries/to_geojson.py` — emit GeoJSON, **one `FeatureCollection` per country**, carrying `name`, `parent`, `version`, `source`, `licence`, and a `bbox` per feature. Validate geometry (closed rings, winding, holes).
- [ ] Geometry **simplification** (Douglas–Peucker) for the baseline layer to hit the ~15–25 MB target.
- [ ] `tools/boundaries/build_bbdb.py` — generate `boundaries.db`: per-layer R-Trees (`rtree_country/state/county`) + `region_*` metadata + `file_version`, from the feature `bbox` members.
- [ ] `tools/boundaries/publish.py` — assemble the baseline bundle, the per-country packs, and `manifest.json` (dataset version + per-pack versions); upload as Release assets to `AgreeDK/OpenSAK-Data`.
- [ ] Keep `tools/` **out of the runtime package** and out of the PyInstaller bundle.

**Acceptance:** running the pipeline on the source data reproducibly produces `boundaries.db`, the baseline GeoJSON, the county packs and `manifest.json`; a first Release of `OpenSAK-Data` exists.
**Risk:** medium — data quality/coverage and simplification tuning. Size: L.

---

## Phase 1 — Core engine (`src/opensak/geo/`)

**Goal:** an offline `TerritoryResolver` that, given coordinates, returns `GeoLocation(country, state, county)` via the two-stage lookup — no GUI, no network.

**Tasks**
- [ ] Add `shapely` to `[project.dependencies]` in [`pyproject.toml`](../pyproject.toml) (Stage 2 point-in-polygon). Keep a pure-Python ray-cast fallback path behind a flag.
- [ ] `geo/store.py` — open `boundaries.db`, resolve a region's pack + feature, lazily load and cache GeoJSON geometry.
- [ ] `geo/boundaries.py` — `TerritoryResolver`: per-layer R-Tree query (Stage 1); on a single box hit return directly; on overlaps run point-in-polygon (Stage 2) over the 2–3 candidates; fill state/country from the county's `parent`.
- [ ] Ship `boundaries.db` + baseline GeoJSON as package data; seed them into `<app-data>/opensak/boundaries/` on first run (resolved via [`config.get_app_data_dir()`](../src/opensak/config.py)).
- [ ] Unit tests in `tests/unit-tests/`: known coordinates → expected territory, covering single-hit, overlap/border, hole/enclave, and no-hit (ocean) cases; a perf check that a 10k batch resolves in seconds.

**Acceptance:** a batch of known points resolves correctly offline from the baseline alone; border cases pick the right region; no network is touched.
**Risk:** medium (geometry correctness). Size: L.

---

## Phase 2 — On-demand packs and updates (`src/opensak/geo/packs.py`)

**Goal:** fetch county packs lazily from `OpenSAK-Data`, cache them locally, and keep both the index and the packs current — all without a project-run server.

**Tasks**
- [ ] `geo/packs.py` — on a county cache miss, download that country's pack from the `AgreeDK/OpenSAK-Data` Release asset URL, write it under `counties/` with an **atomic** temp-then-swap, and serve locally thereafter.
- [ ] **"Download all"** — pre-fetch every pack for full offline coverage.
- [ ] **Update check** — throttled (≈weekly + manual) comparison against the latest `manifest.json`; re-download only the changed `boundaries.db` and any out-of-date *cached* packs, atomically; flag affected caches' `location_dataset` as stale rather than rewriting values.
- [ ] Tests with the network **mocked/stubbed** (mirror `conftest.py`'s offline pattern): cache-miss → fetch → local second lookup; version compare; atomic swap; offline fallback returns the coarser cached layer, never a wrong guess.

**Acceptance:** a missing country fetches once (mocked) then resolves locally; an update detects a newer manifest and refreshes only what changed.
**Risk:** medium (network edge cases, atomicity). Size: M.

---

## Phase 3 — Schema and provenance

**Goal:** store where each territory value came from, so results are auditable and re-runnable.

**Tasks**
- [ ] [`db/models.py`](../src/opensak/db/models.py) — add to `Cache`: `location_source` (`groundspeak`/`computed`), `location_basis` (`posted`/`corrected`), `location_updated` (datetime), `location_dataset` (version string).
- [ ] [`db/database.py`](../src/opensak/db/database.py) — bump `SCHEMA_VERSION` (currently 11) and add an idempotent `ALTER TABLE caches ADD COLUMN …` block using the existing `PRAGMA table_info` pattern.
- [ ] Tests: an existing DB upgrades in place; new columns default to NULL ("unknown / imported").

**Acceptance:** old databases open and migrate cleanly; the four provenance columns exist and are writable.
**Risk:** low. Size: S. (Can land in parallel with Phase 1–2; required by Phase 4.)

---

## Phase 4 — GUI integration and retiring the old engine

**Goal:** wire the engine into the existing Update Location flow, surface provenance and updates, and remove the nearest-neighbour geocoder.

**Tasks**
- [ ] Point `ReverseGeocodeWorker` in [`update_location_dialog.py`](../src/opensak/gui/dialogs/update_location_dialog.py) at `TerritoryResolver`; write the provenance fields per cache.
- [ ] Coordinate basis: **default to posted** (the "use corrected" toggle currently defaults on); keep the scope options (all / missing / this cache / filter).
- [ ] Keep the auto-run after GPX/PQ import; route it through the new engine.
- [ ] Add menu actions: **Download all boundary packs** and **Check for boundary updates**; show a stale indicator when `location_dataset` trails the current dataset, offering a one-click re-run.
- [ ] i18n: add every new `tr()` key to all `lang/*.py`; `test_languages.py` / `test_lang_modules.py` stay green.
- [ ] **Remove** [`geocoder.py`](../src/opensak/geocoder.py) (the `reverse_geocoder` KD-tree and the Nominatim path); drop `reverse_geocoder` (and `pycountry`, if now pipeline-only) from runtime deps.
- [ ] Widget/e2e tests with `qtbot` (mind the PySide worker-mocking segfault gotcha: patch the worker class, not QObject methods on a live instance).

**Acceptance:** the dialog resolves end-to-end via the new engine; import auto-fills; provenance and stale state are visible; all language key tests pass; no reference to `reverse_geocoder` remains.
**Risk:** medium (UI wiring + dep removal). Size: L.

---

## Phase 5 — Packaging and CI

**Goal:** the shipped binaries resolve offline on all three OSes, and CI proves it.

**Tasks**
- [ ] [`opensak.spec`](../opensak.spec) — bundle `boundaries.db` + baseline GeoJSON via `collect_data_files`/`datas`; remove the old `reverse_geocoder` data bundling.
- [ ] Verify `shapely`/GEOS wheels install across the [`tests.yml`](../.github/workflows/tests.yml) matrix (Linux/macOS/Windows, py 3.11/3.12); enable the pure-Python fallback if a platform lacks wheels.
- [ ] Add a real-dependency smoke test (in the spirit of `test_geocoder_deps.py`): import `shapely` and resolve a known coordinate under the build's dependency set, so a missing dep fails CI.
- [ ] Check the install/footprint delta stays within the Phase 0 baseline budget.
- [ ] Ship the ODbL attribution in the app's About/credits.

**Acceptance:** freshly built binaries on Windows/macOS/Linux perform an offline reverse geocode; CI is green including `shapely` and the smoke test.
**Risk:** medium (native wheels are the usual culprit). Size: M.

---

## Sequencing

```
Phase 0 (data)  ──►  Phase 1 (engine)  ──►  Phase 2 (packs/updates)  ──►  Phase 4 (GUI) ──► Phase 5 (CI)
                                   Phase 3 (schema) ───────────────────────┘
```

Phase 3 is small and can be done early, but Phase 4 depends on it. Phase 1 needs Phase 0's `boundaries.db` + baseline to test against. Phase 5 closes out packaging once the engine and GUI are real.

## Risks and open questions

- **Data delivery and quality.** Everything hinges on receiving the polygon files; coverage gaps and stale boundaries are inherited from the source (mitigated by the refresh pipeline and provenance).
- **Simplification vs accuracy.** The baseline budget trades polygon detail for size; counties stay full-resolution because they are fetched on demand.
- **`shapely` on all platforms.** The main packaging risk; the pure-Python fallback is the safety net.
- **Behaviour change.** Default flips to posted coordinates and the nearest-neighbour engine is removed — call this out in the release notes for existing users.
