"""Tests for django_dirt_ratings services."""

import json

import pytest
from django.http import Http404
from django.test import RequestFactory

from django_dirt_ratings.models import ClickedCoordinate, Rating, Ratings
from django_dirt_ratings.services import clicked_coordinate_create, rating_create


@pytest.fixture
def request_factory():
    return RequestFactory()


def _make_request(factory, image, session, *, points=None, url="/rate_partial/"):
    """Build a fake POST request with session data pre-populated."""
    data = {}
    if points is not None:
        data["points"] = json.dumps(points)
    request = factory.post(url, data=data)
    request.session = {
        "image_id": image.pk,
        "session_id": session.pk,
    }
    return request


@pytest.mark.django_db
class TestRatingCreate:
    def test_saves_instance(self, request_factory, fmap_image, fmap_session):
        request = _make_request(request_factory, fmap_image, fmap_session)
        instance = Rating(rating=Ratings.PASS)

        rating_create(instance=instance, request=request)

        assert instance.pk is not None
        assert instance.image == fmap_image
        assert instance.session == fmap_session
        assert instance.rating == Ratings.PASS

    def test_persists_to_db(self, request_factory, fmap_image, fmap_session):
        request = _make_request(request_factory, fmap_image, fmap_session)
        instance = Rating(rating=Ratings.FAIL, source_data_issue=True)

        rating_create(instance=instance, request=request)

        saved = Rating.objects.get(pk=instance.pk)
        assert saved.rating == Ratings.FAIL
        assert saved.source_data_issue is True

    def test_missing_image_raises_404(self, request_factory, fmap_image, fmap_session):
        request = _make_request(request_factory, fmap_image, fmap_session)
        request.session["image_id"] = 999999
        instance = Rating(rating=Ratings.PASS)

        with pytest.raises(Http404):
            rating_create(instance=instance, request=request)


@pytest.mark.django_db
class TestClickedCoordinateCreate:
    def test_no_points_saves_single_row(
        self, request_factory, mask_image, mask_session
    ):
        """When no points JSON is posted, a single ClickedCoordinate is saved."""
        request = _make_request(
            request_factory, mask_image, mask_session, url="/click_partial/"
        )
        instance = ClickedCoordinate()

        clicked_coordinate_create(instance=instance, request=request)

        assert instance.pk is not None
        assert ClickedCoordinate.objects.count() == 1

    def test_empty_points_saves_single_row(
        self, request_factory, mask_image, mask_session
    ):
        """An empty points list should still create one row."""
        request = _make_request(
            request_factory, mask_image, mask_session, points=[], url="/click_partial/"
        )
        instance = ClickedCoordinate()

        clicked_coordinate_create(instance=instance, request=request)

        assert instance.pk is not None
        assert ClickedCoordinate.objects.count() == 1

    def test_multiple_points_bulk_creates(
        self, request_factory, mask_image, mask_session
    ):
        """Multiple points should bulk-create one row per point."""
        points = [
            {"x": 1.0, "y": 2.0},
            {"x": 3.0, "y": 4.0},
            {"x": 5.0, "y": 6.0},
        ]
        request = _make_request(
            request_factory,
            mask_image,
            mask_session,
            points=points,
            url="/click_partial/",
        )
        instance = ClickedCoordinate()

        clicked_coordinate_create(instance=instance, request=request)

        assert ClickedCoordinate.objects.count() == 3
        coords = list(ClickedCoordinate.objects.order_by("x").values_list("x", "y"))
        assert coords == [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]

    def test_bulk_created_share_image_and_session(
        self, request_factory, mask_image, mask_session
    ):
        """All bulk-created rows should reference the same image and session."""
        points = [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}]
        request = _make_request(
            request_factory,
            mask_image,
            mask_session,
            points=points,
            url="/click_partial/",
        )
        instance = ClickedCoordinate()

        clicked_coordinate_create(instance=instance, request=request)

        for cc in ClickedCoordinate.objects.all():
            assert cc.image_id == mask_image.pk
            assert cc.session_id == mask_session.pk

    def test_missing_session_raises_404(
        self, request_factory, mask_image, mask_session
    ):
        request = _make_request(
            request_factory, mask_image, mask_session, url="/click_partial/"
        )
        request.session["session_id"] = 999999
        instance = ClickedCoordinate()

        with pytest.raises(Http404):
            clicked_coordinate_create(instance=instance, request=request)
