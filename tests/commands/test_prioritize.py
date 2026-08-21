"""Tests for the prioritize command (z-score math + DB behavior)."""

from collections.abc import Sequence

import pytest
from django.core.management import call_command

from django_dirt_ratings import models, services
from django_dirt_ratings.management.commands.prioritize import _num, _priorities
from django_dirt_ratings.models import MetricDirection as D


def _nums(priorities: Sequence[float | None]) -> list[float]:
    """Narrow all-scored priorities to floats for comparison assertions."""
    assert None not in priorities
    return [p for p in priorities if p is not None]


PLAN = """
[steps.masks]
order_by = "volume_mm3"
direction = "two_sided"
subgroup = ["space"]

[[steps.masks.measures]]
name = "volume_mm3"
compute = "mask_volume"
"""


class TestPrioritiesMath:
    def test_two_sided_is_symmetric_and_ranks_outlier_top(self):
        got = _nums(_priorities([10.0, 10.0, 10.0, 20.0], D.TWO_SIDED))
        assert got[3] == max(got)  # the deviant value ranks highest
        assert got[0] == got[1] == got[2]  # the identical ones tie

    def test_directions(self):
        higher = _nums(_priorities([1.0, 2.0, 3.0], D.HIGHER_WORSE))
        lower = _nums(_priorities([1.0, 2.0, 3.0], D.LOWER_WORSE))
        assert higher[2] > higher[1] > higher[0]  # bigger is worse
        assert lower[0] > lower[1] > lower[2]  # smaller is worse
        assert lower == [-p for p in higher]

    def test_missing_stays_none(self):
        assert _priorities([1.0, None, 3.0], D.TWO_SIDED)[1] is None

    def test_degenerate_subgroups_are_typical(self):
        assert _priorities([5.0, None], D.TWO_SIDED) == [0.0, None]  # n < 2
        assert _priorities([7.0, 7.0, 7.0], D.TWO_SIDED) == [0.0, 0.0, 0.0]  # sd == 0

    def test_num_coercion(self):
        assert _num(3) == 3.0
        assert _num(True) is None
        assert _num("x") is None
        assert _num(float("inf")) is None


class TestDegeneracyFloor:
    """A subgroup with no meaningful spread must not manufacture priorities.

    Real data (ds001761): MNI-space brain masks are the same template mask, agreeing
    to ~0.1% (CV=0.09%). Z-scoring them anyway gave |z|~1 from rounding noise and
    ranked pristine masks above a native mask that was 6.5% off.
    """

    MNI_LIKE = (1857776.0, 1860576.0, 1860792.0, 1857776.0)  # CV = 0.09%

    def test_near_degenerate_subgroup_is_all_typical(self):
        assert _priorities(self.MNI_LIKE, D.TWO_SIDED) == [0.0, 0.0, 0.0, 0.0]

    def test_floor_can_be_disabled(self):
        got = _nums(_priorities(self.MNI_LIKE, D.TWO_SIDED, min_cv=0.0))
        assert any(p > 0 for p in got)

    def test_real_variation_passes_the_floor(self):
        native = [1362087.7, 1611479.7, 1468599.7, 1387490.2]  # CV = 7.7%
        got = _nums(_priorities(native, D.TWO_SIDED))
        assert got[1] == max(got)  # the +10.6% outlier ranks top

    def test_absolute_floor_overrides_min_cv(self):
        values = [100.0, 100.0, 100.0, 110.0]  # CV = 5% -> passes min_cv
        assert any(p > 0 for p in _nums(_priorities(values, D.TWO_SIDED)))
        # ...but the researcher says spreads under 50 units are noise.
        assert _priorities(values, D.TWO_SIDED, min_spread=50.0) == [0.0, 0.0, 0.0, 0.0]

    def test_robust_score_beats_masking(self):
        """A lone outlier inflates the sd it would be divided by (masking).

        Classic z is also hard-bounded at (n-1)/sqrt(n) = 1.5 for n=4, so it
        saturates; the robust modified z is not bounded and flags it clearly.
        """
        got = _nums(
            _priorities([1000000.0, 1000000.0, 1000000.0, 1500000.0], D.TWO_SIDED)
        )
        assert got[3] > 1.5  # classic z would saturate at exactly 1.5

    def test_majority_identical_still_flags_the_outlier(self):
        """MAD collapses to 0 when >50% of values are identical.

        The mean-absolute-deviation fallback must keep scoring, or a robust floor
        would suppress exactly the scan we want to surface.
        """
        got = _nums(_priorities([1000.0, 1000.0, 1000.0, 5000.0], D.TWO_SIDED))
        assert got[3] > 0 and got[3] == max(got)


def _mask(space, vol):
    n = models.Image.objects.count()
    return models.Image.objects.create(
        img=b"\x89PNG",
        file1=f"f{n}.nii.gz",
        display=0,
        step=models.Step.MASK,
        slice=n,
        raw_metrics={"space": space, "volume_mm3": vol},
    )


@pytest.mark.django_db
class TestPrioritizeCommand:
    def test_subgroups_scored_independently_and_idempotent(self):
        services.plan_apply(name="t", text=PLAN)
        typical = _mask("MNI", 100.0)
        _mask("MNI", 100.0)
        outlier = _mask("MNI", 200.0)
        flat = _mask("native", 5.0)  # a subgroup with no variation
        _mask("native", 5.0)
        _mask("native", 5.0)

        call_command("prioritize")
        typical.refresh_from_db()
        outlier.refresh_from_db()
        flat.refresh_from_db()
        # The MNI outlier has the highest |z|; native (all equal) is typical (0.0).
        assert outlier.priority is not None and typical.priority is not None
        assert outlier.priority > typical.priority
        assert flat.priority == 0.0

        before = {i.id: i.priority for i in models.Image.objects.all()}
        call_command("prioritize")  # idempotent
        after = {i.id: i.priority for i in models.Image.objects.all()}
        assert before == after

    def test_no_order_measure_leaves_priority_null(self):
        services.plan_apply(name="t", text="[steps.masks]\n")  # measured=nothing
        img = _mask("MNI", 100.0)
        call_command("prioritize")
        img.refresh_from_db()
        assert img.priority is None
