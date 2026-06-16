"""Tests for django_dirt_ratings models."""

import pytest
from django.db import IntegrityError

from django_dirt_ratings.models import (
    ClickedCoordinate,
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


class TestRatingsChoices:
    """Ratings enum should expose PASS / UNSURE / FAIL."""

    def test_expected_ratings_exist(self):
        names = {r.name for r in Ratings}
        assert names == {"PASS", "UNSURE", "FAIL"}

    def test_ratings_are_ints(self):
        for value, _label in Ratings.choices:
            assert isinstance(value, int)


class TestDisplayMode:
    """DisplayMode should have X/Y/Z and a get_random helper."""

    def test_expected_modes_exist(self):
        names = {d.name for d in DisplayMode}
        assert names == {"X", "Y", "Z"}

    def test_get_random_returns_valid_choice(self):
        for _ in range(20):
            val = DisplayMode.get_random()
            assert val in DisplayMode.values


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

    def test_to_dict_returns_expected_keys(self):
        img = self._make_image()
        d = img.to_dict()
        assert set(d.keys()) == {"id", "step", "img"}
        assert d["id"] == img.pk

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
class TestClickedCoordinateModel:
    def test_create_clicked_coordinate(self, mask_image, mask_session):
        cc = ClickedCoordinate.objects.create(
            image=mask_image, session=mask_session, x=10.5, y=20.3
        )
        assert cc.pk is not None
        assert cc.x == pytest.approx(10.5)

    def test_nullable_coordinates(self, mask_image, mask_session):
        cc = ClickedCoordinate.objects.create(image=mask_image, session=mask_session)
        assert cc.x is None
        assert cc.y is None
