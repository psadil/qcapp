"""Tests for django_dirt_ratings models."""

import pytest
from django.db import IntegrityError

from django_dirt_ratings.models import (
    Annotation,
    AnnotationCell,
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
            (Step.MASK, "avif"),
            (Step.SPATIAL_NORMALIZATION, "avif"),
            (Step.SURFACE_LOCALIZATION, "avif"),
            (Step.FMAP_COREGISTRATION, "avif"),
            (Step.DTIFIT, "avif"),
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
    def test_annotation_with_cells(self, mask_image, mask_session):
        annotation = Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )
        AnnotationCell.objects.create(
            annotation=annotation, col=3, row=5, rating=Ratings.FAIL
        )
        AnnotationCell.objects.create(
            annotation=annotation, col=3, row=6, rating=Ratings.UNSURE
        )
        assert annotation.cells.count() == 2
        assert set(annotation.cells.values_list("rating", flat=True)) == {
            Ratings.FAIL,
            Ratings.UNSURE,
        }

    def test_empty_annotation_has_no_cells(self, mask_image, mask_session):
        """A submission with nothing marked is an Annotation with zero cells."""
        annotation = Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )
        assert annotation.cells.count() == 0

    def test_cell_unique_per_annotation(self, mask_image, mask_session):
        annotation = Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )
        AnnotationCell.objects.create(
            annotation=annotation, col=1, row=1, rating=Ratings.FAIL
        )
        with pytest.raises(IntegrityError):
            AnnotationCell.objects.create(
                annotation=annotation, col=1, row=1, rating=Ratings.UNSURE
            )

    def test_cells_cascade_delete(self, mask_image, mask_session):
        annotation = Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )
        AnnotationCell.objects.create(
            annotation=annotation, col=1, row=1, rating=Ratings.FAIL
        )
        annotation.delete()
        assert AnnotationCell.objects.count() == 0
