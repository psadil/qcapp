"""Tests for django_dirt_ratings selectors."""

import pytest

from django_dirt_ratings import services
from django_dirt_ratings.exceptions import ApplicationError, NotFound
from django_dirt_ratings.models import (
    DisplayMode,
    Image,
    Ratings,
    Session,
    Step,
)
from django_dirt_ratings.selectors import (
    image_exists,
    image_file_exists,
    image_get,
    image_list,
    image_with_fewest_ratings,
    session_get,
)


def _make_image(step=Step.FMAP_COREGISTRATION, **kwargs):
    defaults = {
        "img": b"\x89PNG",
        "file1": f"file_{Image.objects.count()}.nii.gz",
        "display": DisplayMode.X,
        "step": step,
        "slice": Image.objects.count(),
    }
    defaults.update(kwargs)
    return Image.objects.create(**defaults)


@pytest.mark.django_db
class TestImageGet:
    def test_returns_image(self, mask_image):
        assert image_get(image_id=mask_image.pk) == mask_image

    def test_missing_image_raises(self):
        with pytest.raises(NotFound):
            image_get(image_id=999999)


@pytest.mark.django_db
class TestImageExistsAndList:
    def test_image_exists(self, mask_image):
        assert image_exists(
            file1=mask_image.file1,
            display=mask_image.display,
            step=mask_image.step,
            slice=mask_image.slice,
        )

    def test_image_exists_false_for_unknown(self):
        assert not image_exists(file1="nope.nii.gz", display=0, step=Step.MASK, slice=0)

    def test_image_file_exists(self, mask_image):
        assert image_file_exists(file1=mask_image.file1, step=mask_image.step)
        assert not image_file_exists(file1="nope.nii.gz", step=Step.MASK)

    def test_image_list_filters_by_step(self):
        _make_image(step=Step.MASK)
        _make_image(step=Step.DTIFIT)
        masks = image_list(step=Step.MASK)
        assert all(img.step == Step.MASK for img in masks)
        assert masks.count() == 1

    def test_image_list_respects_limit(self):
        for _ in range(3):
            _make_image(step=Step.MASK)
        assert len(image_list(limit=2)) == 2


@pytest.mark.django_db
class TestSessionGet:
    def test_returns_session(self, mask_session):
        assert session_get(session_id=mask_session.pk) == mask_session

    def test_missing_session_raises(self):
        with pytest.raises(NotFound):
            session_get(session_id=999999)


@pytest.mark.django_db
class TestImageWithFewestRatings:
    def test_returns_image_with_no_ratings(self):
        """With two images, one rated and one not, returns the unrated one."""
        img_rated = _make_image()
        img_unrated = _make_image()
        session = Session.objects.create(step=Step.FMAP_COREGISTRATION)
        services.rating_create(image=img_rated, session=session, rating=Ratings.PASS)

        result = image_with_fewest_ratings(step=Step.FMAP_COREGISTRATION)
        assert result.pk == img_unrated.pk

    def test_raises_on_empty_db(self):
        with pytest.raises(ApplicationError, match="No image found"):
            image_with_fewest_ratings(step=Step.FMAP_COREGISTRATION)

    def test_excludes_last_pk(self):
        """image_with_fewest_ratings should skip the excluded image."""
        img1 = _make_image()
        img2 = _make_image()

        result = image_with_fewest_ratings(
            step=Step.FMAP_COREGISTRATION, exclude=img1.pk
        )
        assert result.pk == img2.pk

    def test_exclude_only_image_raises(self):
        """Excluding the only image should raise ApplicationError."""
        img = _make_image()
        with pytest.raises(ApplicationError, match="No image found"):
            image_with_fewest_ratings(step=Step.FMAP_COREGISTRATION, exclude=img.pk)

    def test_click_step_uses_annotation(self):
        """For MASK step, submissions are Annotations, not Ratings."""
        img_clicked = _make_image(step=Step.MASK)
        img_unclicked = _make_image(step=Step.MASK)
        session = Session.objects.create(step=Step.MASK)
        services.annotation_create(
            image=img_clicked, session=session, grid_cols=28, grid_rows=21, cells=[]
        )

        result = image_with_fewest_ratings(step=Step.MASK)
        assert result.pk == img_unclicked.pk

    def test_counts_submissions_not_cells(self):
        """An image marked with many cells in one review counts as one review."""
        img_many_cells = _make_image(step=Step.MASK)
        img_one_review = _make_image(step=Step.MASK)
        session = Session.objects.create(step=Step.MASK)
        # img_many_cells: one submission, but many marked cells.
        services.annotation_create(
            image=img_many_cells,
            session=session,
            grid_cols=28,
            grid_rows=21,
            cells=[(c, 0, Ratings.FAIL) for c in range(10)],
        )
        # img_one_review: one submission, zero cells (still one review).
        services.annotation_create(
            image=img_one_review, session=session, grid_cols=28, grid_rows=21, cells=[]
        )

        # Both have exactly one submission, so a third image with none is next.
        img_unreviewed = _make_image(step=Step.MASK)
        result = image_with_fewest_ratings(step=Step.MASK)
        assert result.pk == img_unreviewed.pk
