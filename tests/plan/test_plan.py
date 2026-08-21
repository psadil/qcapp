"""Tests for review-plan parsing, validation, and persistence."""

import pytest

from django_dirt_ratings import models, plan, services

VALID = """
name = "demo"

[ordering]
strategy = "anomaly_first"
triage_depth = 2

[steps.masks]
order_by = "volume_mm3"
direction = "two_sided"
subgroup = ["space"]

[[steps.masks.measures]]
name = "volume_mm3"
compute = "mask_volume"
"""


class TestParseValid:
    """VALID is parsed once per test; each test asserts one facet of the result."""

    @pytest.fixture
    def parsed(self) -> plan.Plan:
        return plan.parse(VALID)

    @pytest.fixture
    def mask_plan(self, parsed: plan.Plan) -> plan.StepPlan:
        step_plan = parsed.step_plan(models.Step.MASK)
        if step_plan is None:  # a setup guard, not the assertion under test
            pytest.fail("VALID declares a [steps.masks] table")
        return step_plan

    def test_name(self, parsed):
        assert parsed.name == "demo"

    def test_strategy(self, parsed):
        assert parsed.strategy == models.ReviewStrategy.ANOMALY_FIRST

    def test_triage_depth(self, parsed):
        assert parsed.triage_depth == 2

    def test_reviewable_steps(self, parsed):
        assert parsed.reviewable_steps == (models.Step.MASK,)

    def test_step_order_by(self, mask_plan):
        assert mask_plan.order_by == "volume_mm3"

    def test_step_direction(self, mask_plan):
        assert mask_plan.direction == models.MetricDirection.TWO_SIDED

    def test_step_subgroup(self, mask_plan):
        assert mask_plan.subgroup == ("space",)

    def test_order_by_resolves_to_its_measure(self, mask_plan):
        assert mask_plan.order_measure == plan.Measure(
            name="volume_mm3", compute="mask_volume"
        )

    def test_measure_is_computed(self, mask_plan):
        assert mask_plan.computed_measures == mask_plan.measures

    def test_measure_is_not_a_catalog_measure(self, mask_plan):
        assert mask_plan.catalog_measures == ()


class TestParseEmpty:
    """An empty plan is the default: breadth-first over every step."""

    @pytest.fixture
    def parsed(self) -> plan.Plan:
        return plan.parse("")

    def test_strategy_defaults_to_breadth_first(self, parsed):
        assert parsed.strategy == models.ReviewStrategy.BREADTH_FIRST

    def test_triage_depth_defaults_to_one(self, parsed):
        assert parsed.triage_depth == 1

    def test_declares_no_steps(self, parsed):
        assert parsed.steps == ()


class TestParseCatalogMeasure:
    CATALOG = (
        '[steps.dtifit]\norder_by="fd_mean"\ndirection="higher_worse"\n'
        '[[steps.dtifit.measures]]\nname="fd_mean"\ncatalog="fd_mean"\n'
    )

    @pytest.fixture
    def dtifit_plan(self) -> plan.StepPlan:
        step_plan = plan.parse(self.CATALOG).step_plan(models.Step.DTIFIT)
        if step_plan is None:  # a setup guard, not the assertion under test
            pytest.fail("CATALOG declares a [steps.dtifit] table")
        return step_plan

    def test_measure_is_read_from_the_catalog(self, dtifit_plan):
        assert dtifit_plan.catalog_measures == dtifit_plan.measures

    def test_nothing_is_computed_at_ingest(self, dtifit_plan):
        assert dtifit_plan.computed_measures == ()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"\ncompute="a"\ncatalog="b"',
            id="compute-and-catalog",
        ),
        pytest.param(
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"',
            id="neither-compute-nor-catalog",
        ),
        pytest.param('[steps.masks]\norder_by="nope"', id="order_by-is-not-a-measure"),
        pytest.param("[steps.bogus]\n", id="unknown-step"),
        pytest.param('[ordering]\nstrategy="wat"', id="unknown-strategy"),
        pytest.param("[ordering]\ntriage_depth=0", id="non-positive-triage-depth"),
        pytest.param(
            '[steps.masks]\ndirection="sideways"\n'
            '[[steps.masks.measures]]\nname="v"\ncompute="mask_volume"',
            id="unknown-direction",
        ),
        pytest.param(
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"\ncatalog="c"\n'
            'catalog_suffix="bold"',
            id="cross-dataset-measure-without-match-keys",
        ),
        pytest.param(
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"\ncompute="a"\n'
            'match=["sub"]',
            id="match-on-a-computed-measure",
        ),
    ],
)
def test_invalid_raises_plan_error(text):
    with pytest.raises(plan.PlanError):
        plan.parse(text)


@pytest.fixture
def applied(db) -> models.ReviewPlan:
    """VALID, applied — the arrange+act shared by the persistence tests."""
    return services.plan_apply(name="demo", text=VALID)


@pytest.mark.django_db
class TestApply:
    def test_record_is_active(self, applied):
        assert applied.is_active

    def test_record_is_the_active_record(self, applied):
        assert plan.active_record() == applied

    def test_active_plan_reflects_the_applied_text(self, applied):
        assert plan.active().strategy == models.ReviewStrategy.ANOMALY_FIRST


@pytest.mark.django_db
class TestReapplySameText:
    """Plans are deduped by content hash, so re-applying is a no-op."""

    @pytest.fixture
    def reapplied(self, applied) -> models.ReviewPlan:
        return services.plan_apply(name="demo", text=VALID)

    def test_reuses_the_same_record(self, applied, reapplied):
        assert reapplied.pk == applied.pk

    def test_stores_no_duplicate(self, reapplied):
        assert models.ReviewPlan.objects.count() == 1


@pytest.mark.django_db
class TestApplyDifferentText:
    TRIAGE = VALID.replace('strategy = "anomaly_first"', 'strategy = "triage"')

    @pytest.fixture
    def superseding(self, applied) -> models.ReviewPlan:
        return services.plan_apply(name="b", text=self.TRIAGE)

    def test_new_record_is_active(self, superseding):
        assert superseding.is_active

    def test_previous_record_is_deactivated(self, applied, superseding):
        applied.refresh_from_db()

        assert not applied.is_active

    def test_active_plan_is_the_new_one(self, superseding):
        assert plan.active().strategy == models.ReviewStrategy.TRIAGE


@pytest.mark.django_db
class TestNoPlanApplied:
    def test_there_is_no_active_record(self):
        assert plan.active_record() is None

    def test_active_plan_is_the_default(self):
        assert plan.active().strategy == models.ReviewStrategy.BREADTH_FIRST


@pytest.mark.django_db
class TestSessionPinsServingFacet:
    """A Session copies the plan's serving facet at start-up (see plan module doc)."""

    @pytest.fixture
    def planned_session(self, applied) -> models.Session:
        return services.session_create(step=models.Step.MASK)

    @pytest.fixture
    def unplanned_session(self, db) -> models.Session:
        return services.session_create(step=models.Step.MASK)

    def test_strategy_is_copied_from_the_plan(self, planned_session):
        assert planned_session.strategy == models.ReviewStrategy.ANOMALY_FIRST

    def test_triage_depth_is_copied_from_the_plan(self, planned_session):
        assert planned_session.triage_depth == 2

    def test_strategy_defaults_without_a_plan(self, unplanned_session):
        assert unplanned_session.strategy == models.ReviewStrategy.BREADTH_FIRST

    def test_triage_depth_defaults_without_a_plan(self, unplanned_session):
        assert unplanned_session.triage_depth == 1
