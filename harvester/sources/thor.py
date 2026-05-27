"""THOR WWI Allied bombing register.

The vendored CSV `harvester/data/THOR_WWI.csv` is the declassified US DOD
bombing register for the First World War — 1,441 missions from Aug 1917 to
Nov 1918, all flown by Allied forces (UK / France / Italy / US). The file was
re-encoded latin-1 → UTF-8 when vendored; read it as UTF-8 here.

Each CSV row becomes one `attack` feature located at the **target**
coordinates. The takeoff aerodrome's coordinates are carried in the feature
properties as `takeoff_coord` so the frontend can draw a flight path on
demand. Rows with unparseable target coordinates or date are dropped.

Tagged `attacker: "Allied"` — this dataset is exclusively Allied-flown.
"""

import csv
import datetime
import json
import sys
from pathlib import Path

from .base import Source

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "THOR_WWI.csv"

EPOCH = datetime.date(1914, 1, 1)


def _f(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _t(s):
    if s is None:
        return None
    s = s.strip()
    return s or None


def _coord(lon, lat):
    flon = _f(lon)
    flat = _f(lat)
    if flon is None or flat is None:
        return None
    if not (-180.0 <= flon <= 180.0 and -90.0 <= flat <= 90.0):
        return None
    return [round(flon, 5), round(flat, 5)]


def _day_index(date_iso):
    if not date_iso:
        return None
    try:
        y, m, d = date_iso.strip().split("-")
        return (datetime.date(int(y), int(m), int(d)) - EPOCH).days
    except (ValueError, AttributeError):
        return None


def _row_to_feature(r):
    coord = _coord(r.get("LONGITUDE"), r.get("LATITUDE"))
    if coord is None:
        return None
    msn_date = _t(r.get("MSNDATE"))
    day = _day_index(msn_date)
    if day is None:
        return None
    takeoff = _coord(r.get("TAKEOFFLONGITUDE"), r.get("TAKEOFFLATITUDE"))
    props = {
        "kind": "attack",
        "src": "thor",
        "ref": f"THOR:WWI:{_t(r.get('WWI_ID')) or '?'}",
        "name": _t(r.get("TGTLOCATION")) or "(target)",
        "msn_date": msn_date,
        "day_from": day,
        "day_to": day,
        "attacker": "Allied",
        "country": _t(r.get("COUNTRY")),
        "service": _t(r.get("SERVICE")),
        "unit": _t(r.get("UNIT")),
        "aircraft": _t(r.get("MDS")),
        "operation": _t(r.get("OPERATION")),
        "planes": _i(r.get("NUMBEROFPLANESATTACKING")),
        "departure": _t(r.get("DEPARTURE")),
        "takeoff_time": _t(r.get("TAKEOFFTIME")),
        "takeoff_base": _t(r.get("TAKEOFFBASE")),
        "takeoff_coord": takeoff,
        "weapon_type": _t(r.get("WEAPONTYPE")),
        "weapon_weight_lb": _i(r.get("WEAPONWEIGHT")),
        "bombload_lb": _i(r.get("BOMBLOAD")),
        "altitude_ft": _i(r.get("ALTITUDE")),
        "tgt_country": _t(r.get("TGTCOUNTRY")),
        "tgt_type": _t(r.get("TGTTYPE")),
        "bda": _t(r.get("BDA")),
        "weather": _t(r.get("WEATHER")),
        "enemy_action": _t(r.get("ENEMYACTION")),
        "friendly_casualties": _i(r.get("FRIENDLYCASUALTIES")),
        "friendly_casualties_note": _t(r.get("FRIENDLYCASUALTIES_VERBOSE")),
    }
    props = {k: v for k, v in props.items() if v is not None and v != ""}
    return {
        "type": "Feature",
        "id": props["ref"],
        "geometry": {"type": "Point", "coordinates": coord},
        "properties": props,
    }


def harvest(path=DEFAULT_CSV):
    """Return a list of attack features parsed from the THOR CSV."""
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            f = _row_to_feature(row)
            if f is not None:
                out.append(f)
    return out


SOURCE = Source(
    name="thor",
    title="THOR WWI Allied bombing register (US DOD)",
    kind="attack",
    temporal=True,
    harvest=harvest,
)


if __name__ == "__main__":
    feats = harvest()
    print(f"thor: {len(feats)} features", file=sys.stderr)
    json.dump({"type": "FeatureCollection", "features": feats}, sys.stdout, ensure_ascii=False)
