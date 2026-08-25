"""The review plan — a dataset's QC plan, parsed from ``dirt.toml``.

A plan says which steps are reviewed, how to order them, and what to measure. It
is parsed here into typed, frozen pydantic models and persisted (raw) as a
:class:`models.ReviewPlan` so it travels with the ratings as QC provenance. The
models are the single source of truth for the plan format: ``manage
export_plan_schema`` emits their JSON Schema, so editors validate and complete a
``dirt.toml`` against exactly what :func:`parse` accepts (see
docs/concepts/review-ordering.md). Validation is strict — unknown keys are
rejected, never ignored.

Two facets live in two natural homes (see :mod:`~django_dirt_ratings.services`):

- the **pipeline facet** (``measures`` / ``order_by`` / ``direction`` / ``subgroup``)
  shapes the images — ``render`` measures them and stamps ``Image.review_plan``,
  ``prioritize`` turns the measures into ``Image.priority``;
- the **serving facet** (``strategy``) shapes a review session — it is copied onto
  ``Session`` at start-up.

This module is web-safe: beyond the stdlib it needs only pydantic, which the web
app already loads via django-ninja, so the hot-ish paths (session start, landing)
pay no new import.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Annotated

import pydantic
from pydantic.json_schema import SkipJsonSchema

from django_dirt_ratings import models


class PlanError(ValueError):
    """A review plan is malformed or references something unknown."""


_STRICT = pydantic.ConfigDict(strict=True, frozen=True, extra="forbid")

# TOML yields plain strings/arrays; relax exactly those fields (strict elsewhere,
# so e.g. a boolean or numeric string never coerces into a number).
_LaxStrings = Annotated[tuple[str, ...], pydantic.Field(strict=False)]
_LaxStrategy = Annotated[models.ReviewStrategy, pydantic.Field(strict=False)]
_LaxDirection = Annotated[models.MetricDirection, pydantic.Field(strict=False)]


class Measure(pydantic.BaseModel):
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

    model_config = _STRICT

    name: str = pydantic.Field(
        description="The key this value is stored under in `Image.raw_metrics`."
    )
    compute: str | None = pydantic.Field(
        default=None, description="A metric DIRT computes itself at ingest."
    )
    catalog: str | None = pydantic.Field(
        default=None, description="A metadata key read from the bidslake catalog."
    )
    catalog_suffix: str | None = pydantic.Field(
        default=None,
        description="Cross-dataset: the sibling record's suffix to read `catalog` from.",
    )
    match: _LaxStrings = pydantic.Field(
        default=(),
        description="Cross-dataset: BIDS entities pairing this file to the sibling record.",
    )

    @pydantic.model_validator(mode="after")
    def _one_source(self) -> Measure:
        if bool(self.compute) == bool(self.catalog):
            raise ValueError(
                f"measure {self.name!r}: set exactly one of `compute` or `catalog`"
            )
        cross = self.catalog_suffix is not None or bool(self.match)
        if cross and not self.catalog:
            raise ValueError(
                f"measure {self.name!r}: `catalog_suffix`/`match` apply only to a `catalog` measure"
            )
        if cross and (not self.catalog_suffix or not self.match):
            raise ValueError(
                f"measure {self.name!r}: a cross-dataset catalog measure needs both "
                "`catalog_suffix` and a non-empty `match`"
            )
        return self

    @property
    def is_cross_dataset(self) -> bool:
        """Whether this catalog measure reads from a sibling dataset."""
        return self.catalog_suffix is not None


#: Default relative-variation floor: a subgroup whose spread is under 1% of its own
#: magnitude carries no signal worth ranking (see StepPlan.min_cv).
DEFAULT_MIN_CV = 0.01


def _resolve_step(value: object) -> object:
    """Resolve a ``[steps.<token>]`` table name to its :class:`models.Step`."""
    if isinstance(value, str):
        return models.Step.from_cli_name(value)
    return value


class StepPlan(pydantic.BaseModel):
    """How one step is measured and ordered.

    ``min_cv``/``min_spread`` are the **degeneracy floor**: they answer "does this
    rational subgroup vary enough for a ranking to mean anything?". Without one, a
    subgroup of near-identical values (e.g. brain masks resampled to a common
    template, whose volumes agree to ~0.1%) gets z-scored anyway, manufacturing
    large scores out of rounding noise and burying real outliers from other
    subgroups. Below the floor every member is scored 0.0 (typical) and the step
    falls back to breadth-first for them.
    """

    model_config = _STRICT

    # Injected from the [steps.<token>] table name; hidden from the JSON Schema.
    step: SkipJsonSchema[
        Annotated[models.Step, pydantic.BeforeValidator(_resolve_step)]
    ]
    measures: Annotated[tuple[Measure, ...], pydantic.Field(strict=False)] = ()
    order_by: str | None = pydantic.Field(
        default=None,
        description="The measure (by name) that orders this step; omit for breadth-first.",
    )
    direction: _LaxDirection = pydantic.Field(
        default=models.MetricDirection.TWO_SIDED,
        description="Which values of the `order_by` measure count as atypical.",
    )
    subgroup: _LaxStrings = pydantic.Field(
        default=(),
        description="Entities of the rational subgroup scored within (e.g. ['space']).",
    )
    min_cv: float = pydantic.Field(
        default=DEFAULT_MIN_CV,
        ge=0,
        description="Relative variation floor: subgroup sd / |mean| (unit-free; default 1%).",
    )
    min_spread: float | None = pydantic.Field(
        default=None,
        ge=0,
        description="Absolute variation floor in the measure's own units; overrides min_cv.",
    )

    @pydantic.model_validator(mode="after")
    def _order_by_declared(self) -> StepPlan:
        if self.order_by is not None and self.order_by not in {
            m.name for m in self.measures
        }:
            raise ValueError(
                f"order_by={self.order_by!r} is not a declared measure "
                f"(have {[m.name for m in self.measures]})"
            )
        return self

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


class Ordering(pydantic.BaseModel):
    """The plan's serving facet — how a review session orders images."""

    model_config = _STRICT

    strategy: _LaxStrategy = pydantic.Field(
        default=models.ReviewStrategy.BREADTH_FIRST,
        description="How the next image to review is chosen.",
    )


class StepsTable(pydantic.BaseModel):
    """The reviewed steps — one optional ``[steps.<name>]`` block each.

    One explicit field per :class:`models.Step` (kept in lockstep by the guard
    below) rather than a dynamic mapping, so the generated JSON Schema lists the
    step names and editors can complete them.
    """

    model_config = _STRICT

    masks: StepPlan | None = None
    spatial_normalization: StepPlan | None = None
    surface_localization: StepPlan | None = None
    fmap_coregistration: StepPlan | None = None
    dtifit: StepPlan | None = None

    @pydantic.model_validator(mode="before")
    @classmethod
    def _inject_step(cls, data: object) -> object:
        """Stamp each block with its table name, which becomes the block's ``step``."""
        if not isinstance(data, dict):
            return data
        out: dict[object, object] = {}
        for token, block in data.items():
            if isinstance(block, dict):
                if "step" in block:
                    raise ValueError(
                        f"[steps.{token}]: `step` comes from the table name; do not set it"
                    )
                block = {**block, "step": token}
            out[token] = block
        return out


# Import-time drift guard: a new models.Step must also gain a StepsTable field.
if set(StepsTable.model_fields) != {s.cli_name for s in models.Step}:
    raise RuntimeError("StepsTable fields drifted from models.Step cli names")


class Plan(pydantic.BaseModel):
    """A whole parsed review plan (mirrors the ``dirt.toml`` shape)."""

    model_config = _STRICT

    name: str = pydantic.Field(
        default="", description="Human-readable plan name, stored as QC provenance."
    )
    ordering: Ordering = Ordering()
    steps_table: StepsTable = pydantic.Field(default_factory=StepsTable, alias="steps")

    @property
    def strategy(self) -> models.ReviewStrategy:
        return self.ordering.strategy

    @property
    def steps(self) -> tuple[StepPlan, ...]:
        blocks = (getattr(self.steps_table, f) for f in StepsTable.model_fields)
        return tuple(b for b in blocks if b is not None)

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

    Raises :class:`PlanError` with a precise ``<location>: <problem>`` message on
    any malformed or unknown field, so ``manage plan`` fails loudly rather than a
    typo reaching the serve loop.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise PlanError(f"invalid TOML: {e}") from e
    try:
        return Plan.model_validate(data)
    except pydantic.ValidationError as e:
        errors = e.errors(include_url=False)
        loc = ".".join(str(p) for p in errors[0]["loc"])
        msg = f"{loc}: {errors[0]['msg']}" if loc else errors[0]["msg"]
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        raise PlanError(msg + more) from e


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
