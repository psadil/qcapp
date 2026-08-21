"""Cross-dataset catalog-metric harvest.

A ``catalog`` measure can read an externally-derived metric (an MRIQC IQM, say) that
lives in a *different* dataset from the one DIRT renders. The bidslake cross-dataset
links make that sound: a rendered fMRIPrep file's ``related_datasets(shares_source)``
are the datasets built from the same source, so their ``sub-01`` is the same subject,
and a plan-declared ``match`` on BIDS entities pairs the two records.

Web-safe (duck-typed lake, no neuro imports) so it is unit-testable without the ingest
stack; called from the orchestrator, which owns the real bidslake lake.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from django_dirt_ratings import plan

#: The bidslake relation used to find co-derivatives (datasets sharing a source).
SHARES_SOURCE = "shares_source"


class Lake(Protocol):
    """The bidslake surface the harvest relies on (duck-typed)."""

    def related_datasets(self, dataset_id: str, relation: Any = ...) -> list[str]: ...
    def get(self, **filters: Any) -> Any: ...  # iterable of records with `.metadata`


def harvest_catalog(
    lake: Lake,
    source_dataset_id: str | None,
    source_entities: Mapping[str, Any] | None,
    measures: Sequence[plan.Measure],
) -> dict[str, float | str | None]:
    """Read each cross-dataset ``catalog`` measure for one rendered file.

    For each measure, look in every sibling (``shares_source``) dataset for a record of
    ``catalog_suffix`` paired to this file by the ``match`` entities, and read
    ``catalog`` from its metadata. Only records *carrying the measure's key* count as
    candidates — ``lake.get`` iterates every walked file, so an ordinary ``.json``
    sidecar beside a data file matches the query too, but its registry row owns no
    metadata (``.metadata == {}``); a promoted metadata-only record (an MRIQC IQM
    file) does. A missing or **ambiguous** (>1) candidate yields ``None`` — never a
    guessed value — so ordering only ever surfaces a metric we could pin
    unambiguously to this acquisition.
    """
    cross = [m for m in measures if m.is_cross_dataset]
    if not cross or source_dataset_id is None:
        return {}

    siblings = lake.related_datasets(source_dataset_id, SHARES_SOURCE)
    entities = source_entities or {}
    out: dict[str, float | str | None] = {}
    for measure in cross:
        records: list[Any] = []
        for sibling in siblings:
            filters = {k: entities.get(k) for k in measure.match}
            records.extend(
                lake.get(
                    dataset_id=sibling,
                    suffix=measure.catalog_suffix,
                    extension=".json",
                    **filters,
                )
            )
        # Candidates are the records that actually carry this measure's key: a
        # promoted metadata-only record owns its sidecar metadata, while a plain
        # sidecar's registry row reads {} (its contents live under the described
        # data file's id). The never-guess rule applies among the candidates.
        values = [
            m[measure.catalog]
            for m in (r.metadata for r in records)
            if measure.catalog in m
        ]
        out[measure.name] = values[0] if len(values) == 1 else None
    return out
