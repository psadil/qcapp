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
    image_files_rendered,
    image_get,
    image_list,
    image_with_fewest_ratings,
    session_get,
)

RATED_STEP = Step.FMAP_COREGISTRATION  # submissions are Ratings
CLICKED_STEP = Step.MASK  # submissions are Annotations


@pytest.fixture
def make_image(db):
    """Create an Image with a fresh identity, overriding any field."""

    def _make(step=RATED_STEP, **overrides) -> Image:
        n = Image.objects.count()
        fields = {
            "img": b"\x89PNG",
            "file1": f"file_{n}.nii.gz",
            "display": DisplayMode.X,
            "step": step,
            "slice": n,
        }
        return Image.objects.create(**(fields | overrides))

    return _make


@pytest.mark.django_db
class TestImageGet:
    def test_returns_image(self, mask_image):
        found = image_get(image_id=mask_image.pk)

        assert found == mask_image

    def test_missing_image_raises(self):
        with pytest.raises(NotFound):
            image_get(image_id=999999)


@pytest.mark.django_db
class TestImageExists:
    def test_true_for_a_known_identity(self, mask_image):
        exists = image_exists(
            file1=mask_image.file1,
            display=mask_image.display,
            step=mask_image.step,
            slice=mask_image.slice,
        )

        assert exists

    def test_false_for_an_unknown_identity(self):
        exists = image_exists(file1="nope.nii.gz", display=0, step=Step.MASK, slice=0)

        assert not exists


@pytest.mark.django_db
class TestImageFilesRendered:
    def test_contains_a_known_file(self, mask_image):
        rendered = image_files_rendered(step=mask_image.step)

        assert mask_image.file1 in rendered

    def test_empty_for_an_unrendered_step(self):
        rendered = image_files_rendered(step=Step.MASK)

        assert rendered == set()

    def test_scoped_to_its_step(self, make_image):
        other = make_image(step=Step.DTIFIT)

        rendered = image_files_rendered(step=Step.MASK)

        assert other.file1 not in rendered


@pytest.mark.django_db
class TestImageList:
    def test_filters_by_step(self, make_image):
        mask = make_image(step=Step.MASK)
        make_image(step=Step.DTIFIT)

        listed = image_list(step=Step.MASK)

        assert [img.pk for img in listed] == [mask.pk]

    def test_respects_limit(self, make_image):
        for _ in range(3):
            make_image(step=Step.MASK)

        listed = image_list(limit=2)

        assert len(listed) == 2


@pytest.mark.django_db
class TestSessionGet:
    def test_returns_session(self, mask_session):
        found = session_get(session_id=mask_session.pk)

        assert found == mask_session

    def test_missing_session_raises(self):
        with pytest.raises(NotFound):
            session_get(session_id=999999)


@pytest.mark.django_db
class TestImageWithFewestRatings:
    def test_prefers_the_unrated_image(self, make_image):
        rated = make_image()
        unrated = make_image()
        session = Session.objects.create(step=RATED_STEP)
        services.rating_create(image=rated, session=session, rating=Ratings.PASS)

        found = image_with_fewest_ratings(step=RATED_STEP)

        assert found.pk == unrated.pk

    def test_raises_on_empty_db(self):
        with pytest.raises(ApplicationError, match="No image found"):
            image_with_fewest_ratings(step=RATED_STEP)

    def test_skips_the_excluded_image(self, make_image):
        excluded = make_image()
        other = make_image()

        found = image_with_fewest_ratings(step=RATED_STEP, exclude=excluded.pk)

        assert found.pk == other.pk

    def test_excluding_the_only_image_raises(self, make_image):
        only = make_image()

        with pytest.raises(ApplicationError, match="No image found"):
            image_with_fewest_ratings(step=RATED_STEP, exclude=only.pk)

    def test_click_step_counts_annotations(self, make_image):
        """For MASK step, submissions are Annotations, not Ratings."""
        clicked = make_image(step=CLICKED_STEP)
        unclicked = make_image(step=CLICKED_STEP)
        session = Session.objects.create(step=CLICKED_STEP)
        services.annotation_create(
            image=clicked, session=session, grid_cols=28, grid_rows=21, cells=[]
        )

        found = image_with_fewest_ratings(step=CLICKED_STEP)

        assert found.pk == unclicked.pk

    def test_counts_submissions_not_cells(self, make_image):
        """An image marked with many cells in one review counts as one review."""
        many_cells = make_image(step=CLICKED_STEP)
        no_cells = make_image(step=CLICKED_STEP)
        unreviewed = make_image(step=CLICKED_STEP)
        session = Session.objects.create(step=CLICKED_STEP)
        services.annotation_create(
            image=many_cells,
            session=session,
            grid_cols=28,
            grid_rows=21,
            cells=[(c, 0, Ratings.FAIL) for c in range(10)],
        )
        services.annotation_create(
            image=no_cells, session=session, grid_cols=28, grid_rows=21, cells=[]
        )

        found = image_with_fewest_ratings(step=CLICKED_STEP)

        # Both reviewed images have exactly one submission, so the third is next.
        assert found.pk == unreviewed.pk
