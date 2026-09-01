"""Tests for the prioritize command (z-score math + DB behavior)."""

from collections.abc import Sequence

import pytest
from django.core.management import call_command

from django_dirt_ratings import models, services
from django_dirt_ratings.management.commands.prioritize import _num, _priorities
from django_dirt_ratings.models import MetricDirection as D


def _scores(priorities: Sequence[float | None]) -> list[float]:
    """Narrow an all-scored priority list to floats for comparison assertions."""
    if None in priorities:  # a setup guard, not the assertion under test
        pytest.fail(f"expected every value to be scored, got {priorities!r}")
    return [p for p in priorities if p is not None]


PLAN = """
[steps.masks]
order_by = "mask_volume"
direction = "two_sided"
subgroup = ["space"]
"""


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param(3, 3.0, id="int-widens-to-float"),
        pytest.param(True, None, id="bool-is-not-a-measurement"),
        pytest.param("x", None, id="string-is-not-a-measurement"),
        pytest.param(float("inf"), None, id="non-finite-is-dropped"),
    ],
)
def test_num_coercion(raw, expected):
    coerced = _num(raw)

    assert coerced == expected


class TestTwoSided:
    """One deviant value among three identical ones."""

    @pytest.fixture
    def scores(self) -> list[float]:
        return _scores(_priorities([10.0, 10.0, 10.0, 20.0], D.TWO_SIDED))

    def test_deviant_value_ranks_highest(self, scores):
        assert scores[3] == max(scores)

    def test_identical_values_tie(self, scores):
        assert scores[0] == scores[1] == scores[2]


class TestDirections:
    """The same ascending values, scored under each direction."""

    @pytest.fixture
    def higher_worse(self) -> list[float]:
        return _scores(_priorities([1.0, 2.0, 3.0], D.HIGHER_WORSE))

    @pytest.fixture
    def lower_worse(self) -> list[float]:
        return _scores(_priorities([1.0, 2.0, 3.0], D.LOWER_WORSE))

    def test_higher_worse_ranks_the_largest_top(self, higher_worse):
        assert higher_worse[2] > higher_worse[1] > higher_worse[0]

    def test_lower_worse_ranks_the_smallest_top(self, lower_worse):
        assert lower_worse[0] > lower_worse[1] > lower_worse[2]

    def test_the_directions_are_mirror_images(self, higher_worse, lower_worse):
        assert lower_worse == [-p for p in higher_worse]


class TestMissingAndDegenerate:
    def test_missing_value_stays_none(self):
        priorities = _priorities([1.0, None, 3.0], D.TWO_SIDED)

        assert priorities[1] is None

    @pytest.mark.parametrize(
        "values, expected",
        [
            pytest.param([5.0, None], [0.0, None], id="fewer-than-two-present"),
            pytest.param([7.0, 7.0, 7.0], [0.0, 0.0, 0.0], id="zero-spread"),
        ],
    )
    def test_degenerate_subgroup_is_all_typical(self, values, expected):
        priorities = _priorities(values, D.TWO_SIDED)

        assert priorities == expected


class TestDegeneracyFloor:
    """A subgroup with no meaningful spread must not manufacture priorities.

    Real data (ds001761): MNI-space brain masks are the same template mask, agreeing
    to ~0.1% (CV=0.09%). Z-scoring them anyway gave |z|~1 from rounding noise and
    ranked pristine masks above a native mask that was 6.5% off.
    """

    MNI_LIKE = (1857776.0, 1860576.0, 1860792.0, 1857776.0)  # CV = 0.09%

    def test_near_degenerate_subgroup_is_all_typical(self):
        priorities = _priorities(self.MNI_LIKE, D.TWO_SIDED)

        assert priorities == [0.0, 0.0, 0.0, 0.0]

    def test_floor_can_be_disabled(self):
        scores = _scores(_priorities(self.MNI_LIKE, D.TWO_SIDED, min_cv=0.0))

        assert any(score > 0 for score in scores)

    def test_real_variation_passes_the_floor(self):
        native = [1362087.7, 1611479.7, 1468599.7, 1387490.2]  # CV = 7.7%

        scores = _scores(_priorities(native, D.TWO_SIDED))

        assert scores[1] == max(scores)  # the +10.6% outlier ranks top

    def test_a_five_percent_spread_passes_min_cv(self):
        values = [100.0, 100.0, 100.0, 110.0]  # CV = 5%

        scores = _scores(_priorities(values, D.TWO_SIDED))

        assert any(score > 0 for score in scores)

    def test_absolute_floor_overrides_min_cv(self):
        values = [100.0, 100.0, 100.0, 110.0]  # CV = 5%, but a spread of only 10

        # ...and the researcher says spreads under 50 units are noise.
        priorities = _priorities(values, D.TWO_SIDED, min_spread=50.0)

        assert priorities == [0.0, 0.0, 0.0, 0.0]

    def test_robust_score_beats_masking(self):
        """A lone outlier inflates the sd it would be divided by (masking).

        Classic z is also hard-bounded at (n-1)/sqrt(n) = 1.5 for n=4, so it
        saturates; the robust modified z is not bounded and flags it clearly.
        """
        scores = _scores(
            _priorities([1000000.0, 1000000.0, 1000000.0, 1500000.0], D.TWO_SIDED)
        )

        assert scores[3] > 1.5  # classic z would saturate at exactly 1.5

    def test_majority_identical_still_flags_the_outlier(self):
        """MAD collapses to 0 when >50% of values are identical.

        The mean-absolute-deviation fallback must keep scoring, or a robust floor
        would suppress exactly the scan we want to surface.
        """
        scores = _scores(_priorities([1000.0, 1000.0, 1000.0, 5000.0], D.TWO_SIDED))

        assert scores[3] == max(scores) > 0


@pytest.fixture
def make_mask(db):
    """Create a MASK image and the measurements `prioritize` reads for its file."""

    def _make(space: str, volume: float) -> models.Image:
        n = models.Image.objects.count()
        file1 = f"f{n}.nii.gz"
        services.measured_file_upsert(
            step=models.Step.MASK,
            file1=file1,
            entities={"space": space},
            values={models.ComputedMetric.MASK_VOLUME: volume},
        )
        return services.image_create(
            img=b"\x89PNG",
            file1=file1,
            display=0,
            step=models.Step.MASK,
            slice=n,
        )

    return _make


def _score_of(image: models.Image) -> float:
    """The image's stored priority, reloaded and narrowed to a float."""
    image.refresh_from_db()
    if image.priority is None:  # a setup guard, not the assertion under test
        pytest.fail(f"{image.file1} was left unscored")
    return image.priority


@pytest.mark.django_db
class TestPrioritizeCommand:
    @pytest.fixture
    def scores(self, make_mask) -> dict[str, float]:
        """Two subgroups scored: MNI holds an outlier, native has no variation."""
        services.plan_apply(name="t", text=PLAN)
        images = {
            "typical": make_mask("MNI", 100.0),
            "outlier": make_mask("MNI", 200.0),
            "flat": make_mask("native", 5.0),
        }
        make_mask("MNI", 100.0)
        make_mask("native", 5.0)
        make_mask("native", 5.0)

        call_command("prioritize")

        return {name: _score_of(image) for name, image in images.items()}

    def test_outlier_outranks_its_subgroup(self, scores):
        assert scores["outlier"] > scores["typical"]

    def test_subgroup_without_variation_is_typical(self, scores):
        assert scores["flat"] == 0.0

    def test_rerunning_changes_nothing(self, scores):
        before = dict(models.Image.objects.values_list("id", "priority"))

        call_command("prioritize")

        assert dict(models.Image.objects.values_list("id", "priority")) == before

    def test_no_order_measure_leaves_priority_null(self, make_mask):
        services.plan_apply(name="t", text="[steps.masks]\n")  # orders by nothing
        image = make_mask("MNI", 100.0)

        call_command("prioritize")

        image.refresh_from_db()
        assert image.priority is None

    def test_an_unmeasured_file_is_left_unscored(self, make_mask):
        """A file with no MeasuredFile row sorts after the scored ones."""
        services.plan_apply(name="t", text=PLAN)
        make_mask("MNI", 100.0)
        make_mask("MNI", 200.0)
        orphan = services.image_create(
            img=b"\x89PNG", file1="orphan.nii.gz", display=0, step=models.Step.MASK
        )

        call_command("prioritize")

        orphan.refresh_from_db()
        assert orphan.priority is None
