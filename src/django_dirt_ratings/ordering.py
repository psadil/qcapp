"""Review-ordering strategies — how the next image to review is chosen.

Each strategy encapsulates its own filter + ``order_by`` on a per-step ``Image``
queryset and self-registers by its :class:`~models.ReviewStrategy` key (the same
registry idiom the ingest ``StepSpec`` uses, but class-based via
``__init_subclass__``; cf. Effective Python, "Register Class Existence with
``__init_subclass__``"). Adding a strategy is a new subclass — nothing else changes.

Why breadth-first is the backbone. Submitting a review is what advances the queue:
it increments ``Image.n_reviews`` so a reviewed image sinks. ``priority`` is static
(reviewing never changes it), so it can only ever *re-rank within* a review-depth
band — never be the primary key — or the reviewer would ping-pong between the two
worst images forever. On the first pass (everything at ``n_reviews == 0``) the whole
step is ordered worst-first; then it naturally deepens.
"""

from __future__ import annotations

import abc
from typing import ClassVar

from django.db import models as dm

from django_dirt_ratings import models


class OrderingStrategy(abc.ABC):
    """Base class + registry for review-ordering strategies."""

    key: ClassVar[str]
    _registry: ClassVar[dict[str, type["OrderingStrategy"]]] = {}

    def __init_subclass__(cls, /, key: str, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls.key = key
        OrderingStrategy._registry[key] = cls

    def __init__(self, *, triage_depth: int = 1) -> None:
        self.triage_depth = triage_depth

    @classmethod
    def build(cls, key: str, *, triage_depth: int = 1) -> "OrderingStrategy":
        """Construct the strategy for a ``ReviewStrategy`` key (as stored on a Session)."""
        try:
            subclass = cls._registry[str(key)]
        except KeyError as e:
            raise ValueError(
                f"unknown ordering strategy {key!r}; have {sorted(cls._registry)}"
            ) from e
        return subclass(triage_depth=triage_depth)

    @abc.abstractmethod
    def order(self, qs: dm.QuerySet[models.Image]) -> dm.QuerySet[models.Image]:
        """Filter/order ``qs`` so ``.first()`` is the next image to serve."""
        raise NotImplementedError


class BreadthFirst(OrderingStrategy, key=models.ReviewStrategy.BREADTH_FIRST.value):
    """Fewest reviews first — the default. Backed by the ``image_next`` index."""

    def order(self, qs):
        return qs.order_by("n_reviews", "id")


class AnomalyFirst(OrderingStrategy, key=models.ReviewStrategy.ANOMALY_FIRST.value):
    """Breadth backbone; most-atypical (highest ``priority``) re-ranked within a band.

    NULL priority (no measure) sorts after scored images. Backed by the
    ``image_priority`` index — a single covering seek, no sort.
    """

    def order(self, qs):
        return qs.order_by("n_reviews", dm.F("priority").desc(nulls_last=True), "id")


class Triage(AnomalyFirst, key=models.ReviewStrategy.TRIAGE.value):
    """``anomaly_first`` restricted to under-reviewed images — a failure hunt.

    The ``n_reviews < triage_depth`` filter is the anti-loop guard: reviewing an
    image drops it from the pool, so the run advances and *terminates* when the pool
    empties. It is a serving focus, not data hiding — every image stays in the DB and
    is reviewable under the default strategy.
    """

    def order(self, qs):
        return super().order(qs.filter(n_reviews__lt=self.triage_depth))
