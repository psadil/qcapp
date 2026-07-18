"""Tests for the generalized review-ordering selector (next_image + strategies)."""

import pytest

from django_dirt_ratings import ordering, services
from django_dirt_ratings.exceptions import ApplicationError
from django_dirt_ratings.models import DisplayMode, Image, Ratings, Session, Step
from django_dirt_ratings.selectors import next_image

BREADTH = ordering.BreadthFirst()
ANOMALY = ordering.AnomalyFirst()
STEP = Step.FMAP_COREGISTRATION


def _img(step=STEP, **kwargs):
    n = Image.objects.count()
    defaults = {
        "img": b"\x89PNG",
        "file1": f"f{n}.nii.gz",
        "display": DisplayMode.X,
        "step": step,
        "slice": n,
    }
    defaults.update(kwargs)
    return Image.objects.create(**defaults)


@pytest.mark.django_db
class TestAnomalyFirst:
    def test_highest_priority_served_first(self):
        _img(priority=0.5)
        high = _img(priority=3.0)
        _img(priority=1.0)
        assert next_image(step=STEP, strategy=ANOMALY).pk == high.pk

    def test_null_priority_sorts_after_scored(self):
        scored = _img(priority=0.1)
        _img(priority=None)
        assert next_image(step=STEP, strategy=ANOMALY).pk == scored.pk

    def test_all_null_matches_breadth_first(self):
        first = _img(priority=None)
        _img(priority=None)
        assert next_image(step=STEP, strategy=ANOMALY).pk == first.pk
        assert next_image(step=STEP, strategy=BREADTH).pk == first.pk

    def test_exclude_last(self):
        high = _img(priority=3.0)
        low = _img(priority=1.0)
        assert next_image(step=STEP, strategy=ANOMALY, exclude=high.pk).pk == low.pk

    def test_empty_raises(self):
        with pytest.raises(ApplicationError):
            next_image(step=STEP, strategy=ANOMALY)

    def test_anti_starvation(self):
        """Reviewing the worst image advances the queue instead of ping-ponging.

        priority is static, so if it were the primary sort key the loop would keep
        serving the worst image forever. Because n_reviews is the backbone, reviewing
        the worst sinks it below the still-unreviewed images.
        """
        worst = _img(priority=3.0)
        second = _img(priority=2.0)
        _img(priority=1.0)
        session = Session.objects.create(step=STEP)

        assert next_image(step=STEP, strategy=ANOMALY).pk == worst.pk
        services.rating_create(image=worst, session=session, rating=Ratings.FAIL)
        # Even without excluding it, the reviewed worst no longer dominates.
        assert next_image(step=STEP, strategy=ANOMALY).pk == second.pk


@pytest.mark.django_db
class TestTriage:
    def test_worst_under_reviewed_first(self):
        worst = _img(priority=3.0)
        _img(priority=1.0)
        triage = ordering.OrderingStrategy.build("triage", triage_depth=1)
        assert next_image(step=STEP, strategy=triage).pk == worst.pk

    def test_pool_shrinks_and_terminates(self):
        a = _img(priority=3.0)
        b = _img(priority=1.0)
        session = Session.objects.create(step=STEP)
        triage = ordering.OrderingStrategy.build("triage", triage_depth=1)

        services.rating_create(image=a, session=session, rating=Ratings.PASS)
        services.rating_create(image=b, session=session, rating=Ratings.PASS)
        # Both reviewed → pool empty → raises (a serving focus, not data loss).
        with pytest.raises(ApplicationError):
            next_image(step=STEP, strategy=triage)

    def test_depth_includes_once_reviewed(self):
        a = _img(priority=3.0)
        session = Session.objects.create(step=STEP)
        services.rating_create(image=a, session=session, rating=Ratings.PASS)  # n=1

        with pytest.raises(ApplicationError):
            next_image(
                step=STEP,
                strategy=ordering.OrderingStrategy.build("triage", triage_depth=1),
            )
        deeper = ordering.OrderingStrategy.build("triage", triage_depth=2)
        assert next_image(step=STEP, strategy=deeper).pk == a.pk
