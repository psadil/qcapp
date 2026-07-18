"""The review plan — a dataset's QC plan, parsed from ``dirt.toml``.

A plan says which steps are reviewed, how to order them, and what to measure. It
is parsed here into typed, frozen dataclasses and persisted (raw) as a
:class:`models.ReviewPlan` so it travels with the ratings as QC provenance.

Two facets live in two natural homes (see :mod:`~django_dirt_ratings.services`):

- the **pipeline facet** (``measures`` / ``order_by`` / ``direction`` / ``subgroup``)
  shapes the images — ``render`` measures them and stamps ``Image.review_plan``,
  ``prioritize`` turns the measures into ``Image.priority``;
- the **serving facet** (``strategy`` / ``triage_depth``) shapes a review session —
  it is copied onto ``Session`` at start-up.

This module is web-safe (stdlib ``tomllib`` only, no neuro/ingest imports), so the
web app can read the active plan on the hot-ish paths (session start, landing).
"""

from __future__ import annotations

import dataclasses
import hashlib
import tomllib
from pathlib import Path

from django_dirt_ratings import models


class PlanError(ValueError):
    """A review plan is malformed or references something unknown."""


@dataclasses.dataclass(frozen=True, slots=True)
class Measure:
    """One measured quantity to store in ``Image.raw_metrics`` under ``name``.

    Exactly one source: ``compute`` (a :class:`~management.ingest.measures.MetricExtractor`
    ``key``, computed at ingest) or ``catalog`` (a metadata key read from the bidslake
    catalog).

    A ``catalog`` measure can be **cross-dataset**: when ``catalog_suffix`` and ``match``
    are set, the value is read from a record of that suffix in a *sibling* dataset (one
    sharing a source, see the bidslake cross-dataset links), paired to this file by the
    ``match`` BIDS entities. That is how MRIQC IQMs (in a separate dataset) order an
    fMRIPrep review, e.g. ``catalog="fd_mean", catalog_suffix="bold",
    match=["sub","ses","task","run"]``.
    """

    name: str
    compute: str | None = None
    catalog: str | None = None
    catalog_suffix: str | None = None
    match: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if bool(self.compute) == bool(self.catalog):
            raise PlanError(
                f"measure {self.name!r}: set exactly one of `compute` or `catalog`"
            )
        cross = self.catalog_suffix is not None or bool(self.match)
        if cross and not self.catalog:
            raise PlanError(
                f"measure {self.name!r}: `catalog_suffix`/`match` apply only to a `catalog` measure"
            )
        if cross and (not self.catalog_suffix or not self.match):
            raise PlanError(
                f"measure {self.name!r}: a cross-dataset catalog measure needs both "
                "`catalog_suffix` and a non-empty `match`"
            )

    @property
    def is_cross_dataset(self) -> bool:
        """Whether this catalog measure reads from a sibling dataset."""
        return self.catalog_suffix is not None


#: Default relative-variation floor: a subgroup whose spread is under 1% of its own
#: magnitude carries no signal worth ranking (see StepPlan.min_cv).
DEFAULT_MIN_CV = 0.01


@dataclasses.dataclass(frozen=True, slots=True)
class StepPlan:
    """How one step is measured and ordered.

    ``min_cv``/``min_spread`` are the **degeneracy floor**: they answer "does this
    rational subgroup vary enough for a ranking to mean anything?". Without one, a
    subgroup of near-identical values (e.g. brain masks resampled to a common
    template, whose volumes agree to ~0.1%) gets z-scored anyway, manufacturing
    large scores out of rounding noise and burying real outliers from other
    subgroups. Below the floor every member is scored 0.0 (typical) and the step
    falls back to breadth-first for them.
    """

    step: models.Step
    measures: tuple[Measure, ...] = ()
    order_by: str | None = None
    direction: models.MetricDirection = models.MetricDirection.TWO_SIDED
    subgroup: tuple[str, ...] = ()
    # Relative floor: subgroup sd / |mean| (unit-free; the default guard).
    min_cv: float = DEFAULT_MIN_CV
    # Absolute floor in the measure's own units; overrides min_cv when set.
    min_spread: float | None = None

    @property
    def order_measure(self) -> Measure | None:
        """The measure named by ``order_by`` (validated to exist), or None."""
        if self.order_by is None:
            return None
        return next(m for m in self.measures if m.name == self.order_by)

    @property
    def computed_measures(self) -> tuple[Measure, ...]:
        return tuple(m for m in self.measures if m.compute)

    @property
    def catalog_measures(self) -> tuple[Measure, ...]:
        return tuple(m for m in self.measures if m.catalog)


@dataclasses.dataclass(frozen=True, slots=True)
class Plan:
    """A whole parsed review plan."""

    name: str = ""
    strategy: models.ReviewStrategy = models.ReviewStrategy.BREADTH_FIRST
    triage_depth: int = 1
    steps: tuple[StepPlan, ...] = ()

    def step_plan(self, step: models.Step) -> StepPlan | None:
        return next((s for s in self.steps if s.step == step), None)

    @property
    def reviewable_steps(self) -> tuple[models.Step, ...]:
        """Steps the plan includes (used to gate the landing-page step choices)."""
        return tuple(s.step for s in self.steps)


#: The default plan when none is active: breadth-first over every step.
DEFAULT = Plan()


def content_hash(text: str) -> str:
    """Stable hash of a plan's text, for idempotent persistence/dedup."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse(text: str) -> Plan:
    """Parse and strictly validate a plan from TOML text.

    Raises :class:`PlanError` with a precise message on any malformed field, so
    ``manage plan`` fails loudly rather than a typo reaching the serve loop.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise PlanError(f"invalid TOML: {e}") from e

    ordering = data.get("ordering", {})
    try:
        strategy = models.ReviewStrategy(ordering.get("strategy", "breadth_first"))
    except ValueError as e:
        raise PlanError(
            f"unknown strategy {ordering.get('strategy')!r}; "
            f"choose from {[s.value for s in models.ReviewStrategy]}"
        ) from e

    triage_depth = ordering.get("triage_depth", 1)
    if not isinstance(triage_depth, int) or triage_depth < 1:
        raise PlanError(
            f"triage_depth must be a positive integer, got {triage_depth!r}"
        )

    steps: list[StepPlan] = []
    for token, block in data.get("steps", {}).items():
        try:
            step = models.Step.from_cli_name(token)
        except ValueError as e:
            raise PlanError(str(e)) from e

        measures = tuple(
            Measure(
                name=m["name"],
                compute=m.get("compute"),
                catalog=m.get("catalog"),
                catalog_suffix=m.get("catalog_suffix"),
                match=tuple(m.get("match", [])),
            )
            for m in block.get("measures", [])
        )

        order_by = block.get("order_by")
        if order_by is not None and order_by not in {m.name for m in measures}:
            raise PlanError(
                f"step {token!r}: order_by={order_by!r} is not a declared measure "
                f"(have {[m.name for m in measures]})"
            )

        try:
            direction = models.MetricDirection(block.get("direction", "two_sided"))
        except ValueError as e:
            raise PlanError(
                f"step {token!r}: unknown direction {block.get('direction')!r}"
            ) from e

        min_cv = block.get("min_cv", DEFAULT_MIN_CV)
        if (
            not isinstance(min_cv, (int, float))
            or isinstance(min_cv, bool)
            or min_cv < 0
        ):
            raise PlanError(f"step {token!r}: min_cv must be a non-negative number")
        min_spread = block.get("min_spread")
        if min_spread is not None and (
            not isinstance(min_spread, (int, float))
            or isinstance(min_spread, bool)
            or min_spread < 0
        ):
            raise PlanError(f"step {token!r}: min_spread must be a non-negative number")

        steps.append(
            StepPlan(
                step=step,
                measures=measures,
                order_by=order_by,
                direction=direction,
                subgroup=tuple(block.get("subgroup", [])),
                min_cv=float(min_cv),
                min_spread=None if min_spread is None else float(min_spread),
            )
        )

    return Plan(
        name=data.get("name", ""),
        strategy=strategy,
        triage_depth=triage_depth,
        steps=tuple(steps),
    )


def load(path: Path) -> Plan:
    """Read and parse a plan file."""
    return parse(Path(path).read_text())


def active_record() -> models.ReviewPlan | None:
    """The active persisted plan record, or None if none has been applied."""
    return models.ReviewPlan.objects.filter(is_active=True).first()


def active() -> Plan:
    """The active parsed plan, or :data:`DEFAULT` (breadth-first) if none."""
    record = active_record()
    return parse(record.toml) if record is not None else DEFAULT
