"""Source-plugin contract.

Every harvester data source lives in its own module under `harvester/sources/`
and exposes a `SOURCE` object that conforms to this contract. The orchestrator
in `harvester.harvest` walks the registry in `sources/__init__.py`, calls each
`SOURCE.harvest()`, and merges the results.

Per-source failure is isolated: an exception raised inside one source's
`harvest()` is caught by the orchestrator and the source is marked `stale` in
the manifest. Other sources continue to run and their on-disk output stays
authoritative. Old sources cannot break because of new sources.
"""

from dataclasses import dataclass
from typing import Callable, Iterable

# A "feature" is a GeoJSON Feature dict. Each Source's harvest() must yield
# features whose `properties` already include:
#   - "kind":   "attack" | "battle" | "memorial"
#   - "src":    short source-id ("thor", "wd_battles", ...)
#   - "day_from", "day_to": ints (days since 1914-01-01), or None for atemporal
#     features (e.g. memorials).
# Beyond that the source is free to add any properties it likes.


@dataclass(frozen=True)
class Source:
    name: str           # stable id: "thor", "wd_battles", "osm_memorials"
    title: str          # human description shown in logs and manifest
    kind: str           # produced feature kind ("attack" | "battle" | "memorial")
    temporal: bool      # True if features carry day_from/day_to; False = atemporal
    harvest: Callable[[], Iterable[dict]]
