"""Wikidata · WWI battles, sieges, offensives.

Captures any event that is `wdt:P361 wd:Q361` (part of WWI) and instance of
a military-action subclass — battle, siege, military operation, military
offensive, campaign, naval battle. Land and sea both. Yields one `battle`
feature per event with start/end days and participant labels.

The participant list is then classified into `attacker_side` ("Allied" /
"Central Powers" / "mixed") for the frontend's side filter; this is heuristic
but good enough to colour the marker — the detail panel still lists the raw
participants verbatim.
"""

import json
import sys

from .base import Source
from ..wikidata import parse_point, parse_wd_date, qid_from_uri, query, rows, val

import datetime
EPOCH = datetime.date(1914, 1, 1)

Q_GERMAN_EMPIRE = "Q43287"
Q_AUSTRIA_HUNGARY = "Q131964"
Q_OTTOMAN_EMPIRE = "Q12560"
Q_BULGARIA_1908 = "Q219885"
CENTRAL_POWERS_QIDS = {Q_GERMAN_EMPIRE, Q_AUSTRIA_HUNGARY, Q_OTTOMAN_EMPIRE, Q_BULGARIA_1908}

SPARQL = """\
SELECT DISTINCT ?event ?eventLabel ?start ?end ?coord ?image
       (GROUP_CONCAT(DISTINCT ?participant; separator=",") AS ?participants)
       (GROUP_CONCAT(DISTINCT ?participantLabel; separator="|") AS ?participantLabels)
WHERE {
  ?event wdt:P361 wd:Q361 .
  VALUES ?cls { wd:Q178561 wd:Q645883 wd:Q40231 wd:Q2334719 wd:Q663070 wd:Q1006311 wd:Q19887878 } .
  ?event wdt:P31/wdt:P279* ?cls .
  OPTIONAL { ?event wdt:P580 ?start . }
  OPTIONAL { ?event wdt:P582 ?end . }
  OPTIONAL { ?event wdt:P625 ?coord . }
  OPTIONAL { ?event wdt:P276/wdt:P625 ?coord . }
  OPTIONAL { ?event wdt:P18 ?image . }
  OPTIONAL {
    ?event wdt:P710 ?participant .
    ?participant rdfs:label ?participantLabel . FILTER(LANG(?participantLabel) = "en") .
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?event ?eventLabel ?start ?end ?coord ?image
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


def _classify(participant_qids):
    if not participant_qids:
        return None
    qs = set(participant_qids)
    if qs & CENTRAL_POWERS_QIDS:
        # If both sides present, mark as 'battle' default — the attacker_side
        # field on a battle marker is for tinting only.
        return "Central Powers" if len(qs & CENTRAL_POWERS_QIDS) >= len(qs) / 2 else "mixed"
    return "Allied"


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
        participants_raw = (val(b, "participants") or "").split(",")
        participant_qids = [qid_from_uri(p) for p in participants_raw if p]
        participants_labels = (val(b, "participantLabels") or "").split("|")
        props = {
            "kind": "battle",
            "src": "wd_battles",
            "qid": qid,
            "name": val(b, "eventLabel") or qid,
            "day_from": start,
            "day_to": end,
            "start_date": val(b, "start"),
            "end_date": val(b, "end"),
            "participants": [p for p in participants_labels if p],
            "participant_qids": [p for p in participant_qids if p],
            "attacker_side": _classify(participant_qids),
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
    name="wd_battles",
    title="Wikidata · WWI battles, sieges, offensives",
    kind="battle",
    temporal=True,
    harvest=harvest,
)


if __name__ == "__main__":
    feats = harvest()
    print(f"wd_battles: {len(feats)} features", file=sys.stderr)
    json.dump({"type": "FeatureCollection", "features": feats}, sys.stdout, ensure_ascii=False)
