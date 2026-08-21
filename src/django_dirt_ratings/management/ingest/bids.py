"""Small BIDS helpers shared by the specs."""

from __future__ import annotations

import json
import re
from typing import Any

_ENTITY = re.compile(r"(?:^|[_/])(sub|ses|task|acq|run|space|res|desc)-([A-Za-z0-9]+)")


def parse_entities(name: str) -> dict[str, str]:
    """Parse BIDS ``key-value`` entities out of a filename or relative path."""
    return dict(_ENTITY.findall(name))


def first(lake: Any, **filters: Any) -> Any | None:
    """The first file matching ``filters``, or None (the expected-single lookup).

    ``lake.get`` iterates bidslake's full file registry — every walked file,
    sidecars included — so callers pin ``extension`` to mean one format (all
    current callers do).
    """
    return next(iter(lake.get(**filters)), None)


def intended_for(metadata: dict[str, Any]) -> list[str]:
    """The ``IntendedFor`` targets as a list.

    bidslake stores the merged sidecar value; ``IntendedFor`` comes back as a
    JSON-encoded string (not a parsed list), so decode it here. Tolerates a
    real list, a single string, or a missing key.
    """
    value = metadata.get("IntendedFor")
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return decoded if isinstance(decoded, list) else [decoded]
    return []
