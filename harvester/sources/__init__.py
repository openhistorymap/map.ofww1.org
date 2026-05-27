"""Source registry.

To add a new source:
  1. Create `harvester/sources/<name>.py` exposing a module-level `SOURCE`
     variable conforming to `base.Source`.
  2. Import it here and append to `REGISTRY`.
  3. Optionally add a `__main__` block to the source module so it can be
     run standalone for isolated testing:
        python -m harvester.sources.<name>

The orchestrator iterates `REGISTRY` in declaration order. Sources may be
disabled per-run via the W1M_DISABLE env var (comma-separated names).
"""

from . import osm_memorials, thor, wd_battles, wd_german_raids, wd_memorials

REGISTRY = [
    thor.SOURCE,
    wd_battles.SOURCE,
    wd_german_raids.SOURCE,
    wd_memorials.SOURCE,
    osm_memorials.SOURCE,
]


def by_name(name):
    for s in REGISTRY:
        if s.name == name:
            return s
    return None
