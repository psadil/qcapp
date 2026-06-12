"""Tests for django_dirt_ratings views."""

from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from django_dirt_ratings.models import Rating, Ratings, Session, Step
from django_dirt_ratings.views import (
    DTIFIT_VIEW,
    FMAP_COREGISTRATION_VIEW,
    MASK_VIEW,
    SPATIAL_NORMALIZATION_VIEW,
    SURFACE_LOCALIZATION_VIEW,
)


def _mock_task():
    """Return a MagicMock that looks like a Celery AsyncResult."""
    mock = MagicMock()
    mock.delay.return_value = MagicMock(id="fake-task-id")
    return mock


@pytest.mark.django_db
class TestLayoutView:
    def test_get_renders_index_template(self, client):
        response = client.get(reverse("index"))
        assert response.status_code == 200
        assert "index.html" in [t.name for t in response.templates]

    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_post_with_mask_step_redirects(self, mock_task, client):
        response = client.post(reverse("index"), data={"step": Step.MASK})
        assert response.status_code == 302
        assert MASK_VIEW in response.url

    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_post_creates_session(self, mock_task, client):
        assert Session.objects.count() == 0
        client.post(reverse("index"), data={"step": Step.MASK})
        assert Session.objects.count() == 1

    def test_post_with_invalid_step_rerenders_form(self, client):
        response = client.post(reverse("index"), data={"step": 999})
        assert response.status_code == 200  # form re-rendered


@pytest.mark.django_db
class TestRateViewGet:
    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_fmap_coregistration_renders_rate_template(self, mock_task, client):
        response = client.get(reverse(FMAP_COREGISTRATION_VIEW))
        assert response.status_code == 200
        assert "rate.html" in [t.name for t in response.templates]

    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_mask_renders_click_template(self, mock_task, client):
        response = client.get(reverse(MASK_VIEW))
        assert response.status_code == 200
        assert "click.html" in [t.name for t in response.templates]


@pytest.mark.django_db
class TestRateViewPost:
    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_valid_rating_creates_rating(
        self, mock_task, client, fmap_image, fmap_session
    ):
        # Set up session data (simulate prior GET flow)
        session = client.session
        session["image_id"] = fmap_image.pk
        session["session_id"] = fmap_session.pk
        session.save()

        response = client.post(
            reverse(FMAP_COREGISTRATION_VIEW), data={"rating": Ratings.PASS}
        )

        assert response.status_code == 302
        assert Rating.objects.count() == 1
        rating = Rating.objects.first()
        assert rating.rating == Ratings.PASS
        assert rating.image_id == fmap_image.pk

    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_invalid_rating_returns_404(self, mock_task, client):
        response = client.post(
            reverse(FMAP_COREGISTRATION_VIEW),
            data={},  # missing required 'rating' field
        )
        assert response.status_code == 404
        assert Rating.objects.count() == 0


@pytest.mark.django_db
class TestLayoutViewStepRouting:
    @pytest.mark.parametrize(
        "step, expected_view",
        [
            (Step.MASK, MASK_VIEW),
            (Step.SPATIAL_NORMALIZATION, SPATIAL_NORMALIZATION_VIEW),
            (Step.SURFACE_LOCALIZATION, SURFACE_LOCALIZATION_VIEW),
            (Step.FMAP_COREGISTRATION, FMAP_COREGISTRATION_VIEW),
            (Step.DTIFIT, DTIFIT_VIEW),
        ],
    )
    @patch(
        "django_dirt_ratings.views.tasks.run_db_query_async", new_callable=_mock_task
    )
    def test_step_redirects_to_correct_view(
        self, mock_task, step, expected_view, client
    ):
        response = client.post(reverse("index"), data={"step": step})
        assert response.status_code == 302
        assert response.url == reverse(expected_view)
