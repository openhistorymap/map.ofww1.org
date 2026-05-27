"""Wikidata · WWI war memorials and military cemeteries.

Class enumeration:
  Q575759  — war memorial
  Q1207302 — military cemetery
  Q5183675 — Commonwealth War Graves Commission cemetery
  Q1567164 — memorial monument

Filtered to those whose `wdt:P547` (commemorates) is, transitively, part of
WWI (Q361). Atemporal — `day_from` / `day_to` are null; the frontend treats
these as "always present" when the memorial toggle is on.
"""

import json
import sys

from .base import Source
from ..wikidata import parse_point, parse_wd_date, qid_from_uri, query, rows, val

SPARQL = """\
SELECT DISTINCT ?m ?mLabel ?coord ?countryCode ?inception ?image ?commemorates ?commemoratesLabel
WHERE {
  VALUES ?cls { wd:Q575759 wd:Q1207302 wd:Q5183675 wd:Q1567164 } .
  ?m wdt:P31/wdt:P279* ?cls .
  ?m wdt:P625 ?coord .
  ?m wdt:P547 ?commemorates .
  ?commemorates (wdt:P31|wdt:P361)* wd:Q361 .
  OPTIONAL { ?m wdt:P571 ?inception . }
  OPTIONAL { ?m wdt:P18 ?image . }
  OPTIONAL { ?m wdt:P17/wdt:P297 ?countryCode . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def _https(url):
    if not url:
        return url
    return "https://" + url[7:] if url.startswith("http://") else url


def harvest():
    result = query(SPARQL)
    out = []
    for b in rows(result):
        qid = qid_from_uri(val(b, "m"))
        if not qid:
            continue
        coord = parse_point(val(b, "coord"))
        if not coord:
            continue
        inception_tuple = parse_wd_date(val(b, "inception"))
        props = {
            "kind": "memorial",
            "src": "wd_memorials",
            "qid": qid,
            "name": val(b, "mLabel") or qid,
            "country": val(b, "countryCode"),
            "inception": inception_tuple[0] if inception_tuple else None,
            "commemorates": val(b, "commemoratesLabel"),
            "image": _https(val(b, "image")),
            "day_from": None,
            "day_to": None,
        }
        props = {k: v for k, v in props.items() if v is not None and v != ""}
        out.append({
            "type": "Feature",
            "id": f"wd/{qid}",
            "geometry": {"type": "Point", "coordinates": coord},
            "properties": props,
        })
    return out


SOURCE = Source(
    name="wd_memorials",
    title="Wikidata · WWI memorials and military cemeteries",
    kind="memorial",
    temporal=False,
    harvest=harvest,
)


if __name__ == "__main__":
    feats = harvest()
    print(f"wd_memorials: {len(feats)} features", file=sys.stderr)
    json.dump({"type": "FeatureCollection", "features": feats}, sys.stdout, ensure_ascii=False)
