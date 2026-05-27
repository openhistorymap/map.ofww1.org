# map.ofww1.org

An atlas of First-World-War events: where things were bombed, where battles were fought, and where the dead are remembered. The seed dataset is the **THOR WWI** bombing register (US DOD, declassified, 1,441 missions Aug 1917 – Nov 1918); enriched monthly from Wikidata SPARQL (battles, memorials, military cemeteries) and OpenStreetMap Overpass (war memorials with WWI commemorations).

Sibling project to [`openartmap`](../openartmap/) and [`openculturemap`](../openculturemap/) — same harvester-then-static-GeoJSON shape, same wunderkammer-atlas frontend aesthetic, reframed for a 4-year window of 20th-century violence.

## Layout

- `harvester/` — Python module with a **source-plugin architecture**. Run the whole pipeline with `python -m harvester`; run any single source standalone with `python -m harvester.sources.<name>` (each source dumps its own FeatureCollection to stdout).
  - `harvester/sources/base.py` defines the `Source` dataclass (`name`, `title`, `kind`, `temporal`, `harvest()`).
  - `harvester/sources/__init__.py` is the registry — adding a new data source is **one new file + one line in `REGISTRY`**. Old sources are isolated from new ones; an exception in one source is caught by the orchestrator and the source is marked `stale` in the manifest while everything else continues.
  - Sources shipped today:
    - `sources/thor.py` — vendored `harvester/data/THOR_WWI.csv` (USDoD bombing register, declassified 2016). Allied-flown attacks 1917–1918. ~1,400 features.
    - `sources/wd_battles.py` — Wikidata battles, sieges, offensives part-of WWI (`P361 wd:Q361`).
    - `sources/wd_german_raids.py` — Wikidata Zeppelin / Gotha raids and other German-led aerial attacks (the symmetric counterpart to THOR — without it the atlas reads as US/UK-only).
    - `sources/wd_memorials.py` — Wikidata war memorials and military cemeteries (`P547` commemorates → WWI).
    - `sources/osm_memorials.py` — OSM Overpass per major-belligerent country, `historic=memorial` + WWI signal.
  - Shared transport clients live at the harvester root: `wikidata.py` (WDQS client with adaptive timeout handling, cloned from openartmap) and `overpass.py` (three-mirror Overpass with the WWI-memorial query).
  - `harvest.py` walks the registry, isolates per-source failures, then buckets temporal features by calendar year (1914–1919) into `data/buckets/{year}.geojson` and writes atemporal memorials to `data/memorials.geojson` and the per-source status to `data/manifest.json`.

  Environment knobs (none required):
    - `W1M_ENABLE=thor,wd_battles` — whitelist (run only these sources)
    - `W1M_DISABLE=osm_memorials`   — blacklist (skip these sources)
    - `W1M_COUNTRIES=DE,FR`         — restrict the OSM Overpass country sweep
- `web/` — Static MapLibre frontend. **Day-snapshot slider** (1914-07-28 → 1918-11-11) with a play button is the hero control. Kind toggles: *attacks · battles · memorials*. No build step; deployed as-is to Pages.
- `data/` — Generated. Treat as machine-owned output; do not hand-edit.
- `.github/workflows/harvest.yml` — **manual dispatch only**, no cron. WWI events and battles are essentially a closed historical record; new ones are almost never documented, so a monthly cron is pure noise. Run by hand when Wikidata or OSM has gained meaningful new WWI content, or when the harvester itself changes.

## Data model

Three feature kinds, all `Point` geometries:

- `kind: "attack"` — an air raid recorded in THOR. Lives in the bucket of its `msn_date` year. Properties carry `unit`, `service`, `tgt_location`, `tgt_country`, `tgt_type`, `weapon_weight`, `planes`, `bda` (bomb damage assessment), `takeoff_base`, `takeoff_coord`, `friendly_casualties`. The `ref` is `THOR:WWI:<id>`.
- `kind: "battle"` — a named land/sea battle of WWI from Wikidata. Lives in the bucket of its `start_date` year. Properties: `qid`, `name`, `start_date`, `end_date`, `place_qid`, `country`, optional `image`.
- `kind: "memorial"` — a war memorial commemorating WWI. **Not bucketed by year** — written to `data/memorials.geojson` and shown as an always-present layer when the toggle is on. Properties: `qid?`, `osm_type?`, `osm_id?`, `name`, `commemorates`, `country`, `inception?`, `image?`.

### Time encoding for the slider

Feature `day_from` and `day_to` are integers, **days since 1914-01-01**. THOR missions have `day_from == day_to`; multi-day battles have a real span. The frontend slider scrubs over `[0, 2200]` (a buffer past the armistice). Memorials carry `day_from: null`.

This is more precise than openartmap's year-bucketing because WWI fits in a 4-year window — day resolution is meaningful here in a way it isn't for the 2,800-year span of art history.

## Operational

- Wikidata SPARQL: the WWI corpus is small (≈2,000 battles + ≈3,000 memorials globally), so we don't need openartmap's 25-year chunked windows. A handful of category queries run in <30s each. Same `WdqsTimeout` retry/sub-split logic is kept for robustness.
- Overpass: same three-mirror rotation (`overpass-api.de`, `overpass.kumi.systems`, `overpass.private.coffee`) with 8 s inter-country pacing — keep it.
- WDQS and Overpass `User-Agent` headers carry a contact URL — required by their etiquette. Don't strip it.
- On total failure of a source, the harvester keeps the prior on-disk bucket untouched and marks the source `stale` in the manifest.
- GitHub Pages serves the site at `https://map.ofww1.org` via a custom-domain CNAME. The Pages build source is "GitHub Actions"; the workflow's deploy job uses `actions/deploy-pages@v4`.
- The harvester is **not on a schedule**. Trigger `harvest.yml` manually after meaningful upstream data changes; otherwise the existing `data/` committed to `main` is the source of truth.
- Frontend uses **relative** paths for `data/manifest.json`, `style.css`, `app.js` so the custom domain and any `/staging/`-style subpath both work without a base href.

## THOR CSV notes

- The original file is latin-1 (mojibake on `Saarbrücken`, `Bouès`, etc. when read as UTF-8). The vendored copy is re-encoded to UTF-8 once at import time. **Don't re-encode it on every harvest run** — the encoding is fixed in the vendored copy.
- About 60 rows have missing or unparseable `LATITUDE` / `LONGITUDE`; those are dropped silently. About 200 have missing `TAKEOFFLATITUDE` — those still produce an `attack` feature at the target, just without the flight-path metadata.
- `BDA` (bomb damage assessment) text varies wildly — "ok", "good", "tgt destroyed", multi-sentence narratives. Pass through verbatim; the detail panel renders it as a quoted note.
- The DOD attribution is required by their data licence: every detail panel for a THOR feature carries "Source: THOR Project · US Department of Defense".

## Design

`.impeccable.md` captures the design context. Short version: same Caprasimo display / Vollkorn body lineage as openartmap, but the palette pivots from earth-pigment-warm to a more sombre **sepia + poppy + ink** register fit for a war atlas. Glyphs: a stylised poppy for memorials, crossed-rifles for battles, a falling-bomb mark for THOR attacks.

## House rules

- Local one-off tooling (validators, parsers) runs via `docker run --rm -v "$PWD":/w -w /w python:3-slim …` — the host runtime is too old. Don't dockerize the project itself unless explicitly asked.
- No hard-coded credentials anywhere. There aren't any; keep it that way.
- No tests. Don't claim a change is "tested" just because nothing crashed at import time.
- The THOR CSV is the only large vendored asset (392 KB). Do not vendor the WWII (34 MB) or Vietnam (1.5 GB) THOR files — those belong to sibling projects.
