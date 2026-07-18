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


class TestParse:
    def test_valid(self):
        p = plan.parse(VALID)
        assert p.name == "demo"
        assert p.strategy == models.ReviewStrategy.ANOMALY_FIRST
        assert p.triage_depth == 2
        sp = p.step_plan(models.Step.MASK)
        assert sp is not None
        assert sp.order_by == "volume_mm3"
        assert sp.direction == models.MetricDirection.TWO_SIDED
        assert sp.subgroup == ("space",)
        assert sp.order_measure.compute == "mask_volume"
        assert sp.computed_measures and not sp.catalog_measures
        assert p.reviewable_steps == (models.Step.MASK,)

    def test_empty_is_default_breadth_first(self):
        p = plan.parse("")
        assert p.strategy == models.ReviewStrategy.BREADTH_FIRST
        assert p.triage_depth == 1
        assert p.steps == ()

    def test_catalog_measure(self):
        p = plan.parse(
            '[steps.dtifit]\norder_by="fd_mean"\ndirection="higher_worse"\n'
            '[[steps.dtifit.measures]]\nname="fd_mean"\ncatalog="fd_mean"\n'
        )
        sp = p.step_plan(models.Step.DTIFIT)
        assert sp.catalog_measures[0].catalog == "fd_mean"
        assert not sp.computed_measures

    @pytest.mark.parametrize(
        "text",
        [
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"\ncompute="a"\ncatalog="b"',  # both
            '[steps.masks]\n[[steps.masks.measures]]\nname="x"',  # neither
            '[steps.masks]\norder_by="nope"',  # order_by not a measure
            "[steps.bogus]\n",  # unknown step
            '[ordering]\nstrategy="wat"',  # unknown strategy
            "[ordering]\ntriage_depth=0",  # non-positive depth
            '[steps.masks]\ndirection="sideways"\n'
            '[[steps.masks.measures]]\nname="v"\ncompute="mask_volume"',  # bad direction
        ],
    )
    def test_invalid_raises_plan_error(self, text):
        with pytest.raises(plan.PlanError):
            plan.parse(text)


@pytest.mark.django_db
class TestPersistence:
    def test_apply_persists_and_activates(self):
        record = services.plan_apply(name="demo", text=VALID)
        assert record.is_active
        assert plan.active_record().pk == record.pk
        assert plan.active().strategy == models.ReviewStrategy.ANOMALY_FIRST

    def test_apply_dedups_by_hash(self):
        r1 = services.plan_apply(name="demo", text=VALID)
        r2 = services.plan_apply(name="demo", text=VALID)
        assert r1.pk == r2.pk
        assert models.ReviewPlan.objects.count() == 1

    def test_reapply_switches_active(self):
        r1 = services.plan_apply(name="a", text=VALID)
        r2 = services.plan_apply(
            name="b",
            text=VALID.replace('strategy = "anomaly_first"', 'strategy = "triage"'),
        )
        r1.refresh_from_db()
        assert not r1.is_active and r2.is_active
        assert plan.active().strategy == models.ReviewStrategy.TRIAGE

    def test_no_plan_is_default(self):
        assert plan.active_record() is None
        assert plan.active().strategy == models.ReviewStrategy.BREADTH_FIRST


@pytest.mark.django_db
class TestSessionPinsServingFacet:
    def test_session_create_copies_strategy(self):
        services.plan_apply(name="t", text=VALID)
        session = services.session_create(step=models.Step.MASK)
        assert session.strategy == models.ReviewStrategy.ANOMALY_FIRST
        assert session.triage_depth == 2

    def test_session_defaults_without_plan(self):
        session = services.session_create(step=models.Step.MASK)
        assert session.strategy == models.ReviewStrategy.BREADTH_FIRST
        assert session.triage_depth == 1
