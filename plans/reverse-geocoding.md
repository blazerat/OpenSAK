# Development Plan — Offline Reverse Geocoding (County / State / Country)

Status: Phase 0 + Phase 1 DONE (merged into beta). Phase 3 DONE (branch `60-phase-3-schema`). Phase 2, 4, 5 pending.
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

- [x] Receive the full polygon-file set from Mike (*Lignumaqua*) — full `bb.db3` + all country/state/county zips are now in the worktree (gitignored). Phase 0 is unblocked and done.
- [ ] Create the data repository **`AgreeDK/OpenSAK-Data`** (public) with its own `LICENSE` + attribution file (the polygons are ODbL, not public domain).

## Out of scope (follow-ups)

- Drawing boundary outlines on the Leaflet map (the GeoJSON makes this cheap later).
- Value **locking** and the macro hook — depend on the future custom-fields system.
- Maps and altimetry datasets — separate problems, separate plans (the `OpenSAK-Data` repo is built to host them later).

---

## Phase 0 — Data pipeline and the `OpenSAK-Data` repo ✓ DONE

**Goal:** a reproducible pipeline that turns raw polygon files into the artefacts the app consumes.

**What was built:** a single converter `tools/boundaries/gsak_to_opensak.py` (combines normalise + geojson + bbdb steps). Run: `python3 tools/boundaries/gsak_to_opensak.py --bb-path bb.db3`. `bb.db3` lives at **repo root**, not inside `data/`. Writes `data/boundaries.db` + `data/countries/world.geojson` + `data/states/<cc>.geojson` + `data/counties/<cc>/<pack>.geojson`. Output: 383 countries, 1931 states, 20026 counties.

**Key fixes inside the converter:**
- `_split_antimeridian()`: rings with |Δlon|>180° teleportation edges (Russia, Alaska, Fiji…) are split into independently-closed sub-rings → MultiPolygon. Also detects the synthetic implicit-closing-edge when ring[0] recurs mid-ring.
- Coordinate parser handles all 4 GSAK formats: tab, plain comma, trailing-comma (France/Italy), space-separated (Great Britain).

**Known data gaps (not bugs):** Portugal 0 states, Russia 0 counties — correct per GSAK's source data. 18 state zips + 8 county zips missing from dataset.

**Remaining tasks (deferred to when `OpenSAK-Data` repo exists):**
- [ ] Geometry simplification (Douglas–Peucker) for the baseline layer.
- [ ] `manifest.json` generation and publishing as Release assets to `AgreeDK/OpenSAK-Data`.
- [ ] Keep `tools/` out of the PyInstaller bundle.

**Acceptance:** ✓ pipeline runs reproducibly; `BoundaryStore` + `TerritoryResolver` resolve correctly against real data. `OpenSAK-Data` Release not yet created (blocked on repo creation).

---

## Phase 1 — Core engine (`src/opensak/geo/`) ✓ DONE

**Goal:** an offline `TerritoryResolver` that returns `GeoLocation(country, state, county)`.

**What was built:** `src/opensak/geo/store.py` (`BoundaryStore`) + `src/opensak/geo/boundaries.py` (`TerritoryResolver`). Pure-Python ray-cast PIP (shapely deferred). 14 unit tests in `test_geo.py`. mypy-clean. Nothing imports `geo` in production yet — that's Phase 4. `default_data_dir()` = `$OPENSAK_BOUNDARIES_DIR` or `<repo-root>/data` (parents[3]).

**Remaining tasks:**
- [ ] Seed `boundaries.db` + baseline GeoJSON into `<app-data>/opensak/boundaries/` on first run (Phase 5 packaging concern).

**Acceptance:** ✓ resolves correctly offline; 14 tests pass; mypy green.

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

## Phase 3 — Schema and provenance ✓ DONE

**Goal:** store where each territory value came from, so results are auditable and re-runnable.

**What was built:** four nullable columns on `Cache` (`location_source`, `location_basis`, `location_updated`, `location_dataset`). `SCHEMA_VERSION` bumped 11 → 12; migration 12 is idempotent — uses the existing `PRAGMA table_info` pattern, skips each column if already present. 3 tests: default-NULL, writable, migration-on-old-schema (DROP COLUMN + version rewind).

**Acceptance:** ✓ old databases migrate cleanly; the four provenance columns exist and are writable; 1377 unit tests pass.

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
