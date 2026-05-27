"""Wikidata · German aerial attacks on Allied targets in WWI.

Symmetric counterpart to the THOR source — without this, the atlas reads as
US/UK-only because THOR is exclusively Allied-flown. Captures Zeppelin raids
on Britain, Gotha bomber raids on London/Paris/Italy, and any other aerial
bombardment events whose participant is the German Empire.

Class enumeration:
  Q1131127 — Zeppelin raid
  Q188055  — strategic bombing
  Q1138935 — German strategic bombing during WWI (aggregate event)
  Q2380335 — aerial warfare
  Q3024879 — aerial bombing

Plus a `participant = German Empire` fallback to catch events that are
classified only as generic military operations but are German-led.
"""

import datetime
import json
import sys

from .base import Source
from ..wikidata import parse_point, parse_wd_date, qid_from_uri, query, rows, val

EPOCH = datetime.date(1914, 1, 1)

SPARQL = """\
SELECT DISTINCT ?event ?eventLabel ?start ?end ?coord ?image ?targetLabel
WHERE {
  ?event wdt:P361 wd:Q361 .
  {
    VALUES ?cls { wd:Q1131127 wd:Q188055 wd:Q1138935 wd:Q2380335 wd:Q3024879 } .
    ?event wdt:P31/wdt:P279* ?cls .
  } UNION {
    ?event wdt:P31/wdt:P279* wd:Q645883 .
    ?event wdt:P710 wd:Q43287 .
    FILTER NOT EXISTS { ?event wdt:P31/wdt:P279* wd:Q178561 . }
  }
  OPTIONAL { ?event wdt:P580 ?start . }
  OPTIONAL { ?event wdt:P582 ?end . }
  OPTIONAL { ?event wdt:P625 ?coord . }
  OPTIONAL {
    ?event wdt:P276 ?target . ?target wdt:P625 ?coord .
    ?target rdfs:label ?targetLabel . FILTER(LANG(?targetLabel) = "en") .
  }
  OPTIONAL { ?event wdt:P18 ?image . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def _day_index(date_tuple):
    if not date_tuple:
        return None
    y, m, d = date_tuple
    if y < 1900 or y > 1930:
        return None
    try:
        return (datetime.date(y, m, d) - EPOCH).days
    except (ValueError, OverflowError):
        return None


def _https(url):
    if not url:
        return url
    return "https://" + url[7:] if url.startswith("http://") else url


def harvest():
    result = query(SPARQL)
    out = []
    for b in rows(result):
        qid = qid_from_uri(val(b, "event"))
        if not qid:
            continue
        coord = parse_point(val(b, "coord"))
        if not coord:
            continue
        start = _day_index(parse_wd_date(val(b, "start")))
        end = _day_index(parse_wd_date(val(b, "end")))
        if start is None and end is None:
            continue
        if start is None:
            start = end
        if end is None:
            end = start
        props = {
            "kind": "attack",
            "src": "wd_german_raids",
            "qid": qid,
            "name": val(b, "eventLabel") or qid,
            "tgt_location": val(b, "targetLabel"),
            "day_from": start,
            "day_to": end,
            "start_date": val(b, "start"),
            "end_date": val(b, "end"),
            "attacker": "Central Powers",
            "image": _https(val(b, "image")),
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
    name="wd_german_raids",
    title="Wikidata · German aerial attacks (Zeppelin / Gotha campaigns)",
    kind="attack",
    temporal=True,
    harvest=harvest,
)


if __name__ == "__main__":
    feats = harvest()
    print(f"wd_german_raids: {len(feats)} features", file=sys.stderr)
    json.dump({"type": "FeatureCollection", "features": feats}, sys.stdout, ensure_ascii=False)
