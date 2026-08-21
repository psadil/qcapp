"""Recompute ``Image.priority`` from ``raw_metrics`` per the active review plan.

For each planned step with an ``order_by`` measure this scores that measure *within
a rational subgroup* (SPC: compare like with like — e.g. mask volume within a
template space) and folds in the measure's direction, writing the result to
``Image.priority`` (the anomaly_first/triage ordering key). Web-safe (stdlib only),
idempotent, and a safety valve like ``recount``: rerun it after ``render`` brings in
new measures.

Two statistics with two different jobs (both learned from real data — see
docs/concepts/review-ordering.md):

- the **floor** asks "does this subgroup vary enough for a ranking to mean anything?"
  and uses the *classic* sd//mean, which is deliberately outlier-**sensitive**: an
  outlier is real spread, and a robust MAD-based floor would read 0 whenever a
  majority of values are identical, silently suppressing the very scan we want;
- the **score** asks "how unusual is this one?" and uses a *robust* modified z-score
  (Iglewicz & Hoaglin 1993), which is outlier-**resistant**: a classic z divides by
  an sd the outlier itself inflates (masking), and is hard-bounded at (n-1)/sqrt(n)
  — only 1.5 for n=4 — so it saturates exactly when a scan is badly wrong.

``priority`` is advisory and only ever reorders — never filters or hides an image.
The statistical unit is one whole NIfTI (one ``file1``), not the 15 rendered views
of it, so measures are de-duplicated per file before any statistic is taken.
"""

from __future__ import annotations

import collections
import math
import statistics
from collections.abc import Sequence

from django.core.management.base import BaseCommand

from django_dirt_ratings import models, plan
from django_dirt_ratings.models import MetricDirection

#: Scale factors making MAD (resp. mean absolute deviation) a consistent estimator
#: of sigma for normally distributed data — Iglewicz & Hoaglin (1993).
_MAD_TO_SIGMA = 0.6745
_MEANAD_TO_SIGMA = 0.7979


def _num(value: object) -> float | None:
    """Coerce a raw_metrics value to a finite float, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _has_spread(
    values: list[float], *, min_cv: float, min_spread: float | None
) -> bool:
    """Whether a subgroup varies enough to rank (the degeneracy floor).

    Uses the classic sd on purpose: it is outlier-sensitive, so a single genuinely
    deviant value keeps the subgroup "live" instead of being averaged away.
    ``min_spread`` (absolute, in the measure's units) overrides ``min_cv``.
    """
    sd = statistics.stdev(values)
    if min_spread is not None:
        return sd >= min_spread
    mean = statistics.fmean(values)
    if mean == 0:
        return sd > 0  # CV undefined at a zero mean; any spread counts
    return (sd / abs(mean)) >= min_cv


def _priorities(
    values: Sequence[float | None],
    direction: MetricDirection,
    *,
    min_cv: float = plan.DEFAULT_MIN_CV,
    min_spread: float | None = None,
) -> list[float | None]:
    """Map one subgroup's per-file measure values to priorities (pure; testable).

    None (missing/non-finite measure) stays None — it sorts after scored images.
    A subgroup with no usable spread scores every present value 0.0 (typical).
    """
    present = [v for v in values if v is not None]
    typical: list[float | None] = [None if v is None else 0.0 for v in values]
    if len(present) < 2:
        return typical
    if not _has_spread(present, min_cv=min_cv, min_spread=min_spread):
        return typical

    median = statistics.median(present)
    scale = statistics.median([abs(v - median) for v in present])  # MAD
    factor = _MAD_TO_SIGMA
    if scale == 0:
        # >50% of values identical: MAD collapses. Fall back to the mean absolute
        # deviation so a lone deviant value is still scored (Iglewicz & Hoaglin).
        scale = statistics.fmean([abs(v - median) for v in present])
        factor = _MEANAD_TO_SIGMA
    if scale == 0:
        return typical

    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        z = factor * (v - median) / scale
        match direction:
            case MetricDirection.TWO_SIDED:
                out.append(abs(z))
            case MetricDirection.HIGHER_WORSE:
                out.append(z)
            case MetricDirection.LOWER_WORSE:
                out.append(-z)
    return out


class Command(BaseCommand):
    help = "Recompute Image.priority from raw_metrics per the active review plan."

    def handle(self, *args, **options) -> None:
        active = plan.active()
        updated = 0
        for step_plan in active.steps:
            measure = step_plan.order_measure
            if measure is None:
                continue

            rows = list(
                models.Image.objects.filter(step=step_plan.step.value).values(
                    "id", "priority", "raw_metrics", "file1"
                )
            )
            # De-duplicate to one value per whole NIfTI: a file's 15 rendered views
            # (display x cut) are one observation, not 15. Counting them 15x would
            # dilute the sample-sd correction and skew the floor.
            per_file: dict[tuple, dict[str, float | None]] = collections.defaultdict(
                dict
            )
            row_group: dict[int, tuple[tuple, str]] = {}
            for row in rows:
                rm = row["raw_metrics"] or {}
                key = tuple(rm.get(k) for k in step_plan.subgroup)
                per_file[key][row["file1"]] = _num(rm.get(measure.name))
                row_group[row["id"]] = (key, row["file1"])

            scored: dict[tuple[tuple, str], float | None] = {}
            for key, files in per_file.items():
                names = list(files)
                values = [files[n] for n in names]
                for name, priority in zip(
                    names,
                    _priorities(
                        values,
                        step_plan.direction,
                        min_cv=step_plan.min_cv,
                        min_spread=step_plan.min_spread,
                    ),
                ):
                    scored[(key, name)] = priority

            current = {row["id"]: row["priority"] for row in rows}
            stale = [
                models.Image(id=image_id, priority=scored[group])
                for image_id, group in row_group.items()
                if scored[group] != current[image_id]
            ]
            if stale:
                models.Image.objects.bulk_update(stale, ["priority"])
                updated += len(stale)

        self.stdout.write(
            self.style.SUCCESS(f"Recomputed priority; updated {updated} image(s).")
        )
