"""Overpass client for WWI war memorials.

Same three-mirror rotation as openartmap. The query is tighter though: we want
`historic=memorial` + `memorial=war_memorial` with an explicit WWI commemoration
signal, not every village war memorial regardless of war. The `commemorates`
tag is the cleanest signal; falling back to `start_date` (memorial unveiled
during or shortly after 1914-1918) catches the rest.
"""

import re
import time

import requests

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

UA = "map.ofww1.org/1.0 (+https://openhistorymap.org)"

# `commemorates` is a free-text tag; we accept any value mentioning WWI or one
# of its common names ('Great War', 'Première Guerre mondiale', 'Erster
# Weltkrieg', 'Prima guerra mondiale'). Falling back to `start_date~"^191[4-9]"`
# catches monuments whose `commemorates` tag is missing but whose unveiling
# year clearly places them in the WWI commemorative wave.
QUERY = """
[out:json][timeout:600];
area["ISO3166-1"="{cc}"][admin_level=2]->.a;
(
  nwr["historic"="memorial"]["memorial"="war_memorial"]
     ["commemorates"~"(World War I|WWI|WW1|Great War|First World War|Erster Weltkrieg|Première Guerre|Premiere Guerre|Prima guerra|Primera Guerra|1914|1915|1916|1917|1918)",i](area.a);
  nwr["historic"="memorial"]["memorial"="war_memorial"]
     ["start_date"~"^19(1[4-9]|2[0-5])"](area.a);
  nwr["historic"="memorial"]["commemorates"~"(World War I|WWI|WW1|Great War|First World War|Erster Weltkrieg|1914|1915|1916|1917|1918)",i](area.a);
);
out tags center;
"""


# Countries swept for WWI war memorials. Coverage is intentionally weighted
# toward the major belligerents (FR / DE / GB / IT / BE) and their colonies,
# plus the dominion countries whose memorial landscape is famously WWI-centric
# (AU / NZ / CA). German-side coverage matters: a US/UK-only sweep would
# produce an asymmetric atlas.
COUNTRIES = [
    ("FR", "France"),
    ("DE", "Germany"),
    ("GB", "United Kingdom"),
    ("BE", "Belgium"),
    ("IT", "Italy"),
    ("AT", "Austria"),
    ("CZ", "Czechia"),
    ("HU", "Hungary"),
    ("PL", "Poland"),
    ("RO", "Romania"),
    ("RS", "Serbia"),
    ("SI", "Slovenia"),
    ("HR", "Croatia"),
    ("TR", "Turkey"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("IE", "Ireland"),
    ("NL", "Netherlands"),
    ("LU", "Luxembourg"),
    ("CH", "Switzerland"),
    ("BG", "Bulgaria"),
    ("GR", "Greece"),
    ("RU", "Russia"),
    ("UA", "Ukraine"),
    ("LV", "Latvia"),
    ("LT", "Lithuania"),
    ("EE", "Estonia"),
    ("IL", "Israel"),
    ("ZA", "South Africa"),
    ("IN", "India"),
]


def fetch(cc, attempts_per_mirror=2):
    body = QUERY.format(cc=cc)
    last_err = None
    for mirror in MIRRORS:
        for attempt in range(attempts_per_mirror):
            try:
                r = requests.post(
                    mirror,
                    data={"data": body},
                    timeout=720,
                    headers={"User-Agent": UA},
                )
                if r.status_code in (429, 504):
                    last_err = f"{mirror} -> HTTP {r.status_code}"
                    time.sleep(30 + attempt * 30)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = f"{mirror} -> {e!r}"
                time.sleep(15 + attempt * 30)
    raise RuntimeError(f"all overpass mirrors failed: {last_err}")


def coords(el):
    if el["type"] == "node":
        return [round(el["lon"], 5), round(el["lat"], 5)]
    c = el.get("center")
    if c:
        return [round(c["lon"], 5), round(c["lat"], 5)]
    return None


_YEAR_RE = re.compile(r"-?\d{1,4}")


def parse_year(s):
    if not s:
        return None
    m = _YEAR_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def to_memorial_feature(el, cc):
    tags = el.get("tags") or {}
    if tags.get("historic") != "memorial":
        return None
    lonlat = coords(el)
    if not lonlat:
        return None
    name = tags.get("name") or tags.get("commemorates") or "war memorial"
    inception = parse_year(tags.get("start_date") or tags.get("date"))
    qid = tags.get("wikidata")
    props = {
        "kind": "memorial",
        "src": "osm",
        "osm_type": el["type"],
        "osm_id": el["id"],
        "name": name,
        "commemorates": tags.get("commemorates"),
        "inception": inception,
        "memorial_type": tags.get("memorial"),
        "country": cc,
        "qid": qid,
        "wikipedia": tags.get("wikipedia"),
        "image": tags.get("image") or tags.get("wikimedia_commons"),
        # memorials are atemporal for the slider — they exist 'always' for the
        # purposes of the day-scrubbing UI
        "day_from": None,
        "day_to": None,
    }
    props = {k: v for k, v in props.items() if v is not None and v != ""}
    return {
        "type": "Feature",
        "id": f"osm/{el['type']}/{el['id']}",
        "geometry": {"type": "Point", "coordinates": lonlat},
        "properties": props,
    }
