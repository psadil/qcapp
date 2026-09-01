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

    def test_all_step_values_are_ints(self):
        value_types = {type(value) for value, _label in Step.choices}

        assert value_types == {int}

    def test_expected_steps_exist(self):
        names = {s.name for s in Step}

        assert names == {
            "MASK",
            "SPATIAL_NORMALIZATION",
            "SURFACE_LOCALIZATION",
            "FMAP_COREGISTRATION",
            "DTIFIT",
            "T1W_COREGISTRATION",
        }

    @pytest.mark.parametrize(
        "step, expected",
        [
            (Step.MASK, "avif"),
            (Step.SPATIAL_NORMALIZATION, "avif"),
            (Step.SURFACE_LOCALIZATION, "avif"),
            (Step.FMAP_COREGISTRATION, "avif"),
            (Step.DTIFIT, "avif"),
            (Step.T1W_COREGISTRATION, "avif"),
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
            (Step.T1W_COREGISTRATION, "rating"),
        ],
    )
    def test_related_name(self, step, expected):
        assert step.related_name == expected

    def test_related_name_matches_query_names(self):
        """The enum property must stay in sync with Image's related query names."""
        query_names = {related.name for related in Image._meta.related_objects}

        assert {step.related_name for step in Step} <= query_names


class TestRatingsChoices:
    """Ratings enum should expose PASS / UNSURE / FAIL."""

    def test_expected_ratings_exist(self):
        names = {r.name for r in Ratings}

        assert names == {"PASS", "UNSURE", "FAIL"}

    def test_all_rating_values_are_ints(self):
        value_types = {type(value) for value, _label in Ratings.choices}

        assert value_types == {int}


class TestDisplayMode:
    """DisplayMode should expose the three view axes."""

    def test_expected_modes_exist(self):
        names = {d.name for d in DisplayMode}

        assert names == {"X", "Y", "Z"}


@pytest.fixture
def make_image(db):
    """Create an Image, overriding any field.

    The defaults collide on purpose: identity is (file1, display, step, slice), so
    two bare calls exercise the unique constraint.
    """

    def _make(**overrides) -> Image:
        fields = {
            "img": b"\x89PNG",
            "slice": 0,
            "file1": "test_file.nii.gz",
            "display": DisplayMode.X,
            "step": Step.MASK,
        }
        return Image.objects.create(**(fields | overrides))

    return _make


@pytest.mark.django_db
class TestImageModel:
    def test_created_at_is_set(self, make_image):
        image = make_image()

        assert image.created_at is not None

    def test_updated_at_is_set(self, make_image):
        image = make_image()

        assert image.updated_at is not None

    def test_unique_constraint_prevents_duplicates(self, make_image):
        make_image()

        with pytest.raises(IntegrityError):
            make_image()

    @pytest.mark.parametrize(
        "distinguishing",
        [
            pytest.param({"slice": 1}, id="different-slice"),
            pytest.param({"display": DisplayMode.Y}, id="different-display"),
            pytest.param({"step": Step.DTIFIT}, id="different-step"),
        ],
    )
    def test_unique_constraint_allows_a_distinct_identity(
        self, make_image, distinguishing
    ):
        make_image()

        other = make_image(**distinguishing)

        assert other.pk is not None


@pytest.mark.django_db
class TestSessionModel:
    def test_session_is_saved(self):
        session = Session.objects.create(step=Step.MASK)

        assert session.pk is not None

    def test_session_records_its_step(self):
        session = Session.objects.create(step=Step.MASK)

        assert session.step == Step.MASK

    def test_session_user_defaults_to_none(self):
        session = Session.objects.create(step=Step.MASK)

        assert session.user is None

    def test_session_records_its_user(self):
        session = Session.objects.create(step=Step.DTIFIT, user="testuser")

        assert session.user == "testuser"


@pytest.mark.django_db
class TestRatingModel:
    @pytest.fixture
    def rating(self, mask_image, mask_session) -> Rating:
        return Rating.objects.create(
            image=mask_image, session=mask_session, rating=Ratings.PASS
        )

    @pytest.fixture
    def annotated_rating(self, mask_image, mask_session) -> Rating:
        """A rating carrying every optional field."""
        return Rating.objects.create(
            image=mask_image,
            session=mask_session,
            rating=Ratings.FAIL,
            source_data_issue=True,
            comments="Looks bad",
        )

    def test_rating_is_saved(self, rating):
        assert rating.pk is not None

    def test_rating_records_its_verdict(self, rating):
        assert rating.rating == Ratings.PASS

    def test_source_data_issue_defaults_false(self, rating):
        assert rating.source_data_issue is False

    def test_comments_default_to_empty(self, rating):
        assert rating.comments == ""

    def test_source_data_issue_is_recorded(self, annotated_rating):
        assert annotated_rating.source_data_issue is True

    def test_comments_are_recorded(self, annotated_rating):
        assert annotated_rating.comments == "Looks bad"


@pytest.mark.django_db
class TestAnnotationModel:
    @pytest.fixture
    def annotation(self, mask_image, mask_session) -> Annotation:
        return Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )

    @pytest.fixture
    def marked_annotation(self, annotation) -> Annotation:
        """Two cells marked at two different levels."""
        AnnotationCell.objects.create(
            annotation=annotation, col=3, row=5, rating=Ratings.FAIL
        )
        AnnotationCell.objects.create(
            annotation=annotation, col=3, row=6, rating=Ratings.UNSURE
        )
        return annotation

    def test_marked_cells_are_attached(self, marked_annotation):
        assert marked_annotation.cells.count() == 2

    def test_marked_cells_keep_their_ratings(self, marked_annotation):
        ratings = set(marked_annotation.cells.values_list("rating", flat=True))

        assert ratings == {Ratings.FAIL, Ratings.UNSURE}

    def test_empty_annotation_has_no_cells(self, annotation):
        """A submission with nothing marked is an Annotation with zero cells."""
        assert annotation.cells.count() == 0

    def test_cell_unique_per_annotation(self, annotation):
        AnnotationCell.objects.create(
            annotation=annotation, col=1, row=1, rating=Ratings.FAIL
        )

        with pytest.raises(IntegrityError):
            AnnotationCell.objects.create(
                annotation=annotation, col=1, row=1, rating=Ratings.UNSURE
            )

    def test_cells_cascade_delete(self, marked_annotation):
        marked_annotation.delete()

        assert AnnotationCell.objects.count() == 0
