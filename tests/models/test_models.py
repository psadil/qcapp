"""Tests for django_dirt_ratings models."""

import pytest
from django.contrib.gis import geos
from django.db import IntegrityError

from django_dirt_ratings.models import (
    GEOMETRY_SRID,
    Annotation,
    DisplayMode,
    Image,
    Rating,
    Ratings,
    Session,
    Step,
)


class TestStepChoices:
    """Step enum should expose all expected pipeline stages."""

    def test_all_steps_are_ints(self):
        for value, _label in Step.choices:
            assert isinstance(value, int)

    def test_expected_steps_exist(self):
        names = {s.name for s in Step}
        assert names == {
            "MASK",
            "SPATIAL_NORMALIZATION",
            "SURFACE_LOCALIZATION",
            "FMAP_COREGISTRATION",
            "DTIFIT",
        }

    @pytest.mark.parametrize(
        "step, expected",
        [
            (Step.MASK, "png"),
            (Step.SPATIAL_NORMALIZATION, "png"),
            (Step.SURFACE_LOCALIZATION, "png"),
            (Step.FMAP_COREGISTRATION, "apng"),
            (Step.DTIFIT, "apng"),
        ],
    )
    def test_image_type(self, step, expected):
        assert step.image_type == expected

    @pytest.mark.parametrize(
        "step, expected",
        [
            (Step.MASK, "annotation"),
            (Step.SPATIAL_NORMALIZATION, "annotation"),
            (Step.SURFACE_LOCALIZATION, "annotation"),
            (Step.FMAP_COREGISTRATION, "rating"),
            (Step.DTIFIT, "rating"),
        ],
    )
    def test_related_name(self, step, expected):
        assert step.related_name == expected

    def test_related_name_matches_query_names(self):
        """The enum property must stay in sync with Image's related query names."""
        query_names = {related.name for related in Image._meta.related_objects}
        for step in Step:
            assert step.related_name in query_names


class TestRatingsChoices:
    """Ratings enum should expose PASS / UNSURE / FAIL."""

    def test_expected_ratings_exist(self):
        names = {r.name for r in Ratings}
        assert names == {"PASS", "UNSURE", "FAIL"}

    def test_ratings_are_ints(self):
        for value, _label in Ratings.choices:
            assert isinstance(value, int)


class TestDisplayMode:
    """DisplayMode should expose the three view axes."""

    def test_expected_modes_exist(self):
        names = {d.name for d in DisplayMode}
        assert names == {"X", "Y", "Z"}


@pytest.mark.django_db
class TestImageModel:
    @staticmethod
    def _make_image(**overrides):
        defaults = {
            "img": b"\x89PNG",
            "slice": 0,
            "file1": "test_file.nii.gz",
            "display": DisplayMode.X,
            "step": Step.MASK,
        }
        defaults.update(overrides)
        return Image.objects.create(**defaults)

    def test_timestamps_are_set(self):
        img = self._make_image()
        assert img.created_at is not None
        assert img.updated_at is not None

    def test_unique_constraint_prevents_duplicates(self):
        self._make_image()
        with pytest.raises(IntegrityError):
            self._make_image()

    def test_unique_constraint_allows_different_slice(self):
        self._make_image(slice=0)
        img2 = self._make_image(slice=1)
        assert img2.pk is not None

    def test_unique_constraint_allows_different_display(self):
        self._make_image(display=DisplayMode.X)
        img2 = self._make_image(display=DisplayMode.Y)
        assert img2.pk is not None

    def test_unique_constraint_allows_different_step(self):
        self._make_image(step=Step.MASK)
        img2 = self._make_image(step=Step.DTIFIT)
        assert img2.pk is not None


@pytest.mark.django_db
class TestSessionModel:
    def test_session_creation(self):
        s = Session.objects.create(step=Step.MASK)
        assert s.pk is not None
        assert s.step == Step.MASK
        assert s.user is None

    def test_session_with_user(self):
        s = Session.objects.create(step=Step.DTIFIT, user="testuser")
        assert s.user == "testuser"


@pytest.mark.django_db
class TestRatingModel:
    def test_create_rating(self, mask_image, mask_session):
        r = Rating.objects.create(
            image=mask_image, session=mask_session, rating=Ratings.PASS
        )
        assert r.pk is not None
        assert r.rating == Ratings.PASS
        assert r.source_data_issue is False
        assert r.comments == ""

    def test_rating_with_all_fields(self, mask_image, mask_session):
        r = Rating.objects.create(
            image=mask_image,
            session=mask_session,
            rating=Ratings.FAIL,
            source_data_issue=True,
            comments="Looks bad",
        )
        assert r.source_data_issue is True
        assert r.comments == "Looks bad"


@pytest.mark.django_db
class TestAnnotationModel:
    def test_geometry_round_trip(self, mask_image, mask_session):
        annotation = Annotation.objects.create(
            image=mask_image,
            session=mask_session,
            geometry=geos.Point(10.5, 20.3, srid=GEOMETRY_SRID),
        )
        saved = Annotation.objects.get(pk=annotation.pk)
        assert saved.geometry.x == pytest.approx(10.5)
        assert saved.geometry.y == pytest.approx(20.3)

    def test_nullable_geometry(self, mask_image, mask_session):
        annotation = Annotation.objects.create(image=mask_image, session=mask_session)
        assert annotation.geometry is None
