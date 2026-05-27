"""OpenStreetMap · WWI war memorials per country.

Sweeps `historic=memorial` + `memorial=war_memorial` with a WWI signal in
`commemorates` or `start_date` across the major-belligerent country list in
`harvester.overpass`. Atemporal.

Failures per country are tolerated: a country that times out on Overpass is
logged and skipped; other countries still complete.
"""

import json
import os
import sys
import time

from .base import Source
from .. import overpass


def harvest():
    countries_env = os.environ.get("W1M_COUNTRIES", "").strip()
    if countries_env:
        wanted = {c.strip().upper() for c in countries_env.split(",") if c.strip()}
        countries = [(cc, name) for cc, name in overpass.COUNTRIES if cc in wanted]
    else:
        countries = overpass.COUNTRIES

    out = []
    for i, (cc, name) in enumerate(countries):
        try:
            data = overpass.fetch(cc)
        except Exception as e:
            print(f"  osm_memorials: {cc} {name} failed: {e!r}", file=sys.stderr)
            continue
        n = 0
        for el in data.get("elements", []):
            f = overpass.to_memorial_feature(el, cc)
            if f:
                out.append(f)
                n += 1
        print(f"  osm_memorials: {cc} {name} -> {n}", file=sys.stderr)
        if i < len(countries) - 1:
            time.sleep(8)
    return out


SOURCE = Source(
    name="osm_memorials",
    title="OSM · WWI war memorials per country",
    kind="memorial",
    temporal=False,
    harvest=harvest,
)


if __name__ == "__main__":
    feats = harvest()
    print(f"osm_memorials: {len(feats)} features", file=sys.stderr)
    json.dump({"type": "FeatureCollection", "features": feats}, sys.stdout, ensure_ascii=False)
