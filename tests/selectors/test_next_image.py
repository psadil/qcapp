"""Tests for the generalized review-ordering selector (next_image + strategies)."""

import pytest

from django_dirt_ratings import ordering, services
from django_dirt_ratings.exceptions import ApplicationError
from django_dirt_ratings.models import DisplayMode, Image, Ratings, Session, Step
from django_dirt_ratings.selectors import next_image

BREADTH = ordering.BreadthFirst()
ANOMALY = ordering.AnomalyFirst()
STEP = Step.FMAP_COREGISTRATION


@pytest.fixture
def make_image(db):
    """Create a reviewable Image with a fresh identity, overriding any field."""

    def _make(step=STEP, **overrides) -> Image:
        n = Image.objects.count()
        fields = {
            "img": b"\x89PNG",
            "file1": f"f{n}.nii.gz",
            "display": DisplayMode.X,
            "step": step,
            "slice": n,
        }
        return Image.objects.create(**(fields | overrides))

    return _make


@pytest.fixture
def session(db) -> Session:
    return Session.objects.create(step=STEP)


@pytest.mark.django_db
class TestAnomalyFirst:
    def test_highest_priority_served_first(self, make_image):
        make_image(priority=0.5)
        high = make_image(priority=3.0)
        make_image(priority=1.0)

        served = next_image(step=STEP, strategy=ANOMALY)

        assert served.pk == high.pk

    def test_null_priority_sorts_after_scored(self, make_image):
        scored = make_image(priority=0.1)
        make_image(priority=None)

        served = next_image(step=STEP, strategy=ANOMALY)

        assert served.pk == scored.pk

    @pytest.mark.parametrize("strategy", [ANOMALY, BREADTH], ids=["anomaly", "breadth"])
    def test_all_null_falls_back_to_insertion_order(self, make_image, strategy):
        first = make_image(priority=None)
        make_image(priority=None)

        served = next_image(step=STEP, strategy=strategy)

        assert served.pk == first.pk

    def test_exclude_last(self, make_image):
        high = make_image(priority=3.0)
        low = make_image(priority=1.0)

        served = next_image(step=STEP, strategy=ANOMALY, exclude=high.pk)

        assert served.pk == low.pk

    def test_empty_raises(self):
        with pytest.raises(ApplicationError):
            next_image(step=STEP, strategy=ANOMALY)

    def test_anti_starvation(self, make_image, session):
        """Reviewing the worst image advances the queue instead of ping-ponging.

        priority is static, so if it were the primary sort key the loop would keep
        serving the worst image forever. Because n_reviews is the backbone, reviewing
        the worst sinks it below the still-unreviewed images.
        """
        worst = make_image(priority=3.0)
        second = make_image(priority=2.0)
        make_image(priority=1.0)
        services.rating_create(image=worst, session=session, rating=Ratings.FAIL)

        # Nothing is excluded: the reviewed worst simply no longer dominates.
        served = next_image(step=STEP, strategy=ANOMALY)

        assert served.pk == second.pk


@pytest.mark.django_db
class TestTriage:
    SHALLOW = ordering.OrderingStrategy.build("triage", triage_depth=1)
    DEEPER = ordering.OrderingStrategy.build("triage", triage_depth=2)

    def test_worst_under_reviewed_first(self, make_image):
        worst = make_image(priority=3.0)
        make_image(priority=1.0)

        served = next_image(step=STEP, strategy=self.SHALLOW)

        assert served.pk == worst.pk

    def test_pool_shrinks_and_terminates(self, make_image, session):
        """Reviewing drops an image from the pool, so a run ends instead of looping."""
        for priority in (3.0, 1.0):
            image = make_image(priority=priority)
            services.rating_create(image=image, session=session, rating=Ratings.PASS)

        # Pool empty → raises. That is a serving focus ending, not data loss.
        with pytest.raises(ApplicationError):
            next_image(step=STEP, strategy=self.SHALLOW)

    def test_depth_one_excludes_a_reviewed_image(self, make_image, session):
        reviewed = make_image(priority=3.0)
        services.rating_create(image=reviewed, session=session, rating=Ratings.PASS)

        with pytest.raises(ApplicationError):
            next_image(step=STEP, strategy=self.SHALLOW)

    def test_depth_two_includes_a_once_reviewed_image(self, make_image, session):
        reviewed = make_image(priority=3.0)
        services.rating_create(image=reviewed, session=session, rating=Ratings.PASS)

        served = next_image(step=STEP, strategy=self.DEEPER)

        assert served.pk == reviewed.pk
