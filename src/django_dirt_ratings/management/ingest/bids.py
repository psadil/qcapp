"""Small BIDS helpers shared by the specs."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_ENTITY = re.compile(r"(?:^|[_/])(sub|ses|task|acq|run|space|res|desc)-([A-Za-z0-9]+)")


def parse_entities(name: str) -> dict[str, str]:
    """Parse BIDS ``key-value`` entities out of a filename or relative path."""
    return dict(_ENTITY.findall(name))


def index_by(
    lake: Any,
    keys: Sequence[str],
    *,
    where: Callable[[Any], bool] | None = None,
    **filters: Any,
) -> dict[tuple, Any]:
    """One query's matching files, keyed by their ``keys`` entity values.

    The batched replacement for a per-candidate single-file lookup: one
    ``lake.get`` round-trip (~50 ms regardless of result size) builds the index,
    and each candidate is then a dict lookup. ``lake.get`` iterates bidslake's
    full file registry — every walked file, sidecars included — so callers pin
    ``extension`` to mean one format (all current callers do).

    A key matched by more than one file is ambiguous: it is stored as ``None``
    (and warned about once) so lookups skip it, never silently taking either
    candidate.

    ``where`` narrows the result *before* that ambiguity check, for a distinction
    ``lake.get`` cannot express (an entity's value prefix, say). Filtering the
    returned dict instead would let the rejects collide with the wanted file first
    and blank the key.
    """
    index: dict[tuple, Any] = {}
    for f in lake.get(**filters):
        if where is not None and not where(f):
            continue
        key = tuple(f.entities.get(k) for k in keys)
        if key in index:
            if index[key] is not None:
                logger.warning(
                    "ambiguous %s=%s under %s; skipping the key", keys, key, filters
                )
            index[key] = None
        else:
            index[key] = f
    return index


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
