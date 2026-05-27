"""Minimal Wikidata Query Service client. Plain GET requests, polite retries.

WDQS enforces a 60s server-side timeout per query. Beyond that the endpoint
returns HTTP 500 with a Java TimeoutException in the body — we surface that as
a Python WdqsTimeout so the caller can subdivide the chunk and try again.

Cloned from openartmap/harvester/wikidata.py; kept verbatim so the two atlases
stay in sync. The only change is the UA string.
"""

import time

import requests

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "map.ofww1.org/1.0 (https://github.com/openhistorymap/map.ofww1.org; OpenHistoryMap)"


class WdqsTimeout(Exception):
    pass


_TIMEOUT_BODY_MARKERS = (
    "TimeoutException",
    "QueryTimeoutException",
    "QueuedThreadPool",
    "java.util.concurrent.ExecutionException",
)


def query(sparql, attempts=3, http_timeout=180):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(
                ENDPOINT,
                params={"query": sparql, "format": "json"},
                headers={
                    "User-Agent": UA,
                    "Accept": "application/sparql-results+json",
                },
                timeout=http_timeout,
            )
            if r.status_code in (429, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(30 + 20 * i)
                continue
            if r.status_code == 500:
                body = r.text or ""
                if any(m in body for m in _TIMEOUT_BODY_MARKERS):
                    raise WdqsTimeout("WDQS server-side timeout")
                last = f"HTTP 500: {body[:200]}"
                time.sleep(20 + 20 * i)
                continue
            r.raise_for_status()
            text = r.text
            tail = text[-2048:] if len(text) > 2048 else text
            if any(m in tail for m in _TIMEOUT_BODY_MARKERS):
                raise WdqsTimeout("WDQS soft timeout (truncated 200 OK)")
            return r.json()
        except WdqsTimeout:
            raise
        except requests.Timeout:
            last = "http client timeout"
            time.sleep(15 + 15 * i)
        except Exception as e:
            last = repr(e)
            time.sleep(15 + 15 * i)
    raise RuntimeError(f"WDQS failed: {last}")


def rows(result):
    return result.get("results", {}).get("bindings", [])


def val(binding, key):
    cell = binding.get(key)
    if not cell:
        return None
    return cell.get("value")


def qid_from_uri(uri):
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1]


def parse_wd_date(iso):
    """WDQS dates look like '+1916-02-21T00:00:00Z'. Return a (year, month, day)
    tuple of ints, or None on failure. Day/month default to 1 if undefined."""
    if not iso:
        return None
    s = iso
    sign = 1
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        sign = -1
        s = s[1:]
    try:
        date_part = s.split("T", 1)[0]
        y_str, m_str, d_str = (date_part.split("-") + ["1", "1"])[:3]
        return sign * int(y_str), max(1, int(m_str)), max(1, int(d_str))
    except (ValueError, IndexError):
        return None


def parse_point(wkt):
    """'Point(12.49 41.89)' -> [12.49, 41.89], else None."""
    if not wkt or not wkt.startswith("Point("):
        return None
    inner = wkt[6:-1]
    parts = inner.split()
    if len(parts) != 2:
        return None
    try:
        lon = float(parts[0])
        lat = float(parts[1])
    except ValueError:
        return None
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return [round(lon, 5), round(lat, 5)]
