"""Orchestrator for map.ofww1.org sources.

Walks `harvester.sources.REGISTRY` and runs each source's `harvest()` in
isolation. Per-source exceptions are caught and the source is marked `stale`
in the manifest; other sources continue. Old sources cannot break because of
new sources — that's the point of the plugin architecture.

Bucketing:
  - Temporal sources (those with day_from on every feature) are merged and
    bucketed by calendar year into `data/buckets/{year}.geojson`.
  - Atemporal sources (memorials) are merged into `data/memorials.geojson`,
    deduped by `qid` (Wikidata wins over OSM).

Output:
  - `data/buckets/{year}.geojson`
  - `data/memorials.geojson`
  - `data/manifest.json` — includes per-source status (ok/stale/disabled)

Environment overrides:
  W1M_ENABLE=thor,wd_battles   only run these sources (whitelist)
  W1M_DISABLE=osm_memorials    skip these sources (blacklist)
  W1M_COUNTRIES=DE,FR          override OSM Overpass country sweep
"""

import datetime
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import sources

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BUCKET_DIR = DATA_DIR / "buckets"

EPOCH = datetime.date(1914, 1, 1)
ARMISTICE_DAY = (datetime.date(1918, 11, 11) - EPOCH).days


def _env_set(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return {s.strip() for s in raw.split(",") if s.strip()}


def _year_of(day):
    return (EPOCH + datetime.timedelta(days=day)).year


def _select_sources():
    enable = _env_set("W1M_ENABLE")
    disable = _env_set("W1M_DISABLE") or set()
    if enable is not None:
        return [s for s in sources.REGISTRY if s.name in enable and s.name not in disable]
    return [s for s in sources.REGISTRY if s.name not in disable]


def _bucket_temporal(features):
    buckets = {}
    dropped = 0
    for f in features:
        day = f["properties"].get("day_from")
        if day is None:
            dropped += 1
            continue
        y = _year_of(day)
        buckets.setdefault(y, []).append(f)
    return buckets, dropped


def _dedupe_memorials(features):
    """Prefer Wikidata-tagged memorials over duplicate OSM rows. Dedupe by qid
    when present; fall back to (osm_type, osm_id) for OSM-only memorials."""
    by_qid = {}
    seen_osm = set()
    out = []
    # First pass: Wikidata-sourced memorials (they always carry a qid)
    for f in features:
        p = f["properties"]
        if p.get("src") == "wd_memorials":
            q = p.get("qid")
            if q:
                by_qid[q] = f
                out.append(f)
    # Second pass: OSM memorials, drop any with a matching wikidata tag
    for f in features:
        p = f["properties"]
        if p.get("src") == "wd_memorials":
            continue
        q = p.get("qid")
        if q and q in by_qid:
            continue
        key = (p.get("osm_type"), p.get("osm_id"))
        if all(key) and key in seen_osm:
            continue
        if all(key):
            seen_osm.add(key)
        out.append(f)
    return out


def _write_buckets(buckets, stale_years):
    BUCKET_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for key in sorted(buckets.keys()):
        path = BUCKET_DIR / f"{key}.geojson"
        fc = {"type": "FeatureCollection", "features": buckets[key]}
        with path.open("w", encoding="utf-8") as fh:
            json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
        written.append({
            "key": key,
            "year": key,
            "file": f"buckets/{path.name}",
            "count": len(buckets[key]),
            "stale": key in stale_years,
        })
    return written


def _write_memorials(features):
    path = DATA_DIR / "memorials.geojson"
    fc = {"type": "FeatureCollection", "features": features}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
    return {"file": "memorials.geojson", "count": len(features)}


def _write_manifest(buckets_meta, memorials_meta, totals, source_status, generated_at):
    manifest = {
        "generated_at": generated_at,
        "epoch": EPOCH.isoformat(),
        "armistice_day": ARMISTICE_DAY,
        "totals": totals,
        "buckets": buckets_meta,
        "memorials": memorials_meta,
        "sources": source_status,
    }
    with (DATA_DIR / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BUCKET_DIR.mkdir(parents=True, exist_ok=True)

    enabled = _select_sources()
    print(
        f"map.ofww1.org harvest · {len(enabled)} sources enabled: "
        f"{', '.join(s.name for s in enabled)}",
        flush=True,
    )
    started = datetime.datetime.now(datetime.timezone.utc)

    temporal_features = []
    memorial_features = []
    source_status = {}

    for src in enabled:
        print(f"\n[{src.name}] {src.title}", flush=True)
        t0 = time.monotonic()
        try:
            feats = list(src.harvest())
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f"  !! failed after {elapsed:.1f}s: {e!r}", flush=True)
            traceback.print_exc()
            source_status[src.name] = {"status": "stale", "error": repr(e), "count": 0}
            continue
        elapsed = time.monotonic() - t0
        if src.temporal:
            temporal_features.extend(feats)
        else:
            memorial_features.extend(feats)
        source_status[src.name] = {
            "status": "ok",
            "count": len(feats),
            "elapsed_seconds": round(elapsed, 1),
            "kind": src.kind,
        }
        print(f"  -> {len(feats)} features in {elapsed:.1f}s", flush=True)
        time.sleep(2)  # polite pacing between sources

    # Note disabled sources in the manifest so the frontend can show 'this
    # source was skipped this run' rather than 'this source returned nothing'.
    for src in sources.REGISTRY:
        if src.name not in source_status:
            source_status[src.name] = {"status": "disabled", "count": 0, "kind": src.kind}

    print(f"\nbucketing {len(temporal_features)} temporal features by year...", flush=True)
    buckets, dropped = _bucket_temporal(temporal_features)
    if dropped:
        print(f"  (dropped {dropped} temporal features without a usable day_from)", flush=True)

    stale_years = set()
    if any(s.get("status") == "stale" and source_status[name].get("kind") in ("attack", "battle")
           for name, s in source_status.items()):
        stale_years.update(range(1914, 1920))

    memorial_features = _dedupe_memorials(memorial_features)

    buckets_meta = _write_buckets(buckets, stale_years)
    memorials_meta = _write_memorials(memorial_features)

    totals = {
        "features": len(temporal_features) + len(memorial_features),
        "attacks": sum(1 for f in temporal_features if f["properties"].get("kind") == "attack"),
        "battles": sum(1 for f in temporal_features if f["properties"].get("kind") == "battle"),
        "memorials": len(memorial_features),
    }
    finished = datetime.datetime.now(datetime.timezone.utc)
    _write_manifest(
        buckets_meta,
        memorials_meta,
        totals,
        source_status,
        finished.isoformat(timespec="seconds"),
    )
    elapsed = (finished - started).total_seconds()
    print(f"\ndone in {elapsed:.0f}s. totals: {totals}", flush=True)
    failures = [n for n, s in source_status.items() if s.get("status") == "stale"]
    if failures:
        print(f"  stale sources: {failures}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
