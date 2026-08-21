"""Tests for django_dirt_ratings services."""

import contextlib
import typing

import pytest
from django.core.exceptions import ValidationError

from django_dirt_ratings.models import (
    Annotation,
    AnnotationCell,
    DisplayMode,
    Image,
    Rating,
    Ratings,
    ReviewPlan,
    Step,
)
from django_dirt_ratings.services import (
    ImageRow,
    annotation_create,
    image_create,
    image_delete,
    image_upsert,
    image_upsert_many,
    rating_create,
    session_create,
)


def _row(**overrides) -> ImageRow:
    """One `image_upsert_many` row; identity is (file1, display, step, slice)."""
    row: ImageRow = {
        "img": b"a",
        "file1": "f.nii.gz",
        "file2": None,
        "display": DisplayMode.X,
        "step": Step.MASK,
        "slice": 0,
    }
    return typing.cast("ImageRow", row | overrides)


@pytest.mark.django_db
class TestSessionCreate:
    def test_session_is_saved(self):
        session = session_create(step=Step.MASK)

        assert session.pk is not None

    def test_records_its_step(self):
        session = session_create(step=Step.MASK)

        assert session.step == Step.MASK

    def test_user_defaults_to_none(self):
        session = session_create(step=Step.MASK)

        assert session.user is None

    def test_records_its_user(self):
        session = session_create(step=Step.DTIFIT, user="rater1")

        assert session.user == "rater1"

    def test_invalid_step_raises(self):
        with pytest.raises(ValidationError):
            session_create(step=999)


@pytest.fixture
def rejected_rating(fmap_image, fmap_session):
    """An attempt to rate with a value the model rejects; the failure is the point."""
    with contextlib.suppress(ValidationError):
        rating_create(image=fmap_image, session=fmap_session, rating=999)


@pytest.mark.django_db
class TestRatingCreate:
    @pytest.fixture
    def rating(self, fmap_image, fmap_session) -> Rating:
        return rating_create(
            image=fmap_image, session=fmap_session, rating=Ratings.PASS
        )

    @pytest.fixture
    def reloaded_failure(self, fmap_image, fmap_session) -> Rating:
        """A FAIL flagged as a source-data issue, read back from the database."""
        created = rating_create(
            image=fmap_image,
            session=fmap_session,
            rating=Ratings.FAIL,
            source_data_issue=True,
        )
        return Rating.objects.get(pk=created.pk)

    def test_rating_is_saved(self, rating):
        assert rating.pk is not None

    def test_links_the_image(self, rating, fmap_image):
        assert rating.image == fmap_image

    def test_links_the_session(self, rating, fmap_session):
        assert rating.session == fmap_session

    def test_records_the_verdict(self, rating):
        assert rating.rating == Ratings.PASS

    def test_verdict_round_trips(self, reloaded_failure):
        assert reloaded_failure.rating == Ratings.FAIL

    def test_source_data_issue_round_trips(self, reloaded_failure):
        assert reloaded_failure.source_data_issue is True

    def test_invalid_rating_raises(self, fmap_image, fmap_session):
        with pytest.raises(ValidationError):
            rating_create(image=fmap_image, session=fmap_session, rating=999)

    def test_invalid_rating_writes_no_row(self, rejected_rating):
        assert Rating.objects.count() == 0


@pytest.mark.django_db
class TestReviewCounter:
    """Image.n_reviews is maintained by the services layer (see selectors)."""

    def test_a_fresh_image_has_no_reviews(self, fmap_image):
        assert fmap_image.n_reviews == 0

    def test_each_rating_increments_the_counter(self, fmap_image, fmap_session):
        rating_create(image=fmap_image, session=fmap_session, rating=Ratings.PASS)
        rating_create(image=fmap_image, session=fmap_session, rating=Ratings.FAIL)

        fmap_image.refresh_from_db()

        assert fmap_image.n_reviews == 2

    def test_annotation_counts_once_regardless_of_cells(self, mask_image, mask_session):
        annotation_create(
            image=mask_image,
            session=mask_session,
            grid_cols=28,
            grid_rows=21,
            cells=[(c, 0, Ratings.FAIL) for c in range(5)],
        )

        mask_image.refresh_from_db()

        # One submission == one review, even though five cells were marked.
        assert mask_image.n_reviews == 1

    def test_invalid_rating_does_not_increment(self, fmap_image, rejected_rating):
        fmap_image.refresh_from_db()

        assert fmap_image.n_reviews == 0


@pytest.mark.django_db
class TestImageCreate:
    @pytest.fixture
    def image(self) -> Image:
        return image_create(
            img=b"\x89PNG",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )

    def test_image_is_saved(self, image):
        assert image.pk is not None

    def test_stores_the_bytes(self, image):
        assert bytes(image.img) == b"\x89PNG"


@pytest.mark.django_db
class TestImageDelete:
    def test_removes_the_row(self, mask_image):
        pk = mask_image.pk

        image_delete(image=mask_image)

        assert not Image.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestImageUpsert:
    """The same identity upserted twice refreshes one row rather than adding one."""

    @pytest.fixture
    def created(self) -> Image:
        return image_upsert(
            img=b"first",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )

    @pytest.fixture
    def updated(self, created) -> Image:
        return image_upsert(
            img=b"second",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )

    def test_reuses_the_same_row(self, created, updated):
        assert updated.pk == created.pk

    def test_stores_no_duplicate(self, updated):
        assert Image.objects.count() == 1

    def test_refreshes_the_bytes(self, updated):
        assert bytes(Image.objects.get().img) == b"second"

    def test_persists_measures(self):
        image = image_upsert(
            img=b"x",
            file1="g.nii.gz",
            display=DisplayMode.X,
            step=Step.DTIFIT,
            slice=None,
            raw_metrics={"fd_mean": 0.3},
        )

        image.refresh_from_db()

        assert image.raw_metrics == {"fd_mean": 0.3}


@pytest.mark.django_db
class TestImageUpsertMany:
    @pytest.fixture
    def bulk_created(self, db) -> None:
        image_upsert_many(images=[_row(slice=0), _row(slice=1)])

    @pytest.fixture
    def reupserted(self, bulk_created) -> Image:
        """One of the two identities re-upserted with new bytes (ON CONFLICT)."""
        image_upsert_many(images=[_row(slice=0, img=b"A")])
        return Image.objects.get(file1="f.nii.gz", slice=0)

    def test_creates_every_row(self, bulk_created):
        assert Image.objects.count() == 2

    def test_reupsert_adds_no_duplicate(self, reupserted):
        assert Image.objects.count() == 2

    def test_reupsert_refreshes_the_bytes(self, reupserted):
        assert bytes(reupserted.img) == b"A"


@pytest.mark.django_db
class TestUpsertManyKeepsPriority:
    """Ingest owns the measures; `prioritize` owns the score derived from them."""

    @pytest.fixture
    def review_plan(self, db) -> ReviewPlan:
        return ReviewPlan.objects.create(name="p", content_hash="h", toml="")

    @pytest.fixture
    def ingested(self, review_plan) -> Image:
        image_upsert_many(
            images=[
                _row(
                    raw_metrics={"space": "MNI", "volume_mm3": 100.0},
                    review_plan_id=review_plan.pk,
                )
            ]
        )
        return Image.objects.get(file1="f.nii.gz", slice=0)

    @pytest.fixture
    def rerendered(self, ingested, review_plan) -> Image:
        """A prioritize run scored the image; then ingest re-rendered it."""
        Image.objects.filter(pk=ingested.pk).update(priority=2.5)
        image_upsert_many(
            images=[
                _row(
                    img=b"A",
                    raw_metrics={"space": "MNI", "volume_mm3": 150.0},
                    review_plan_id=review_plan.pk,
                )
            ]
        )
        ingested.refresh_from_db()
        return ingested

    def test_stores_the_measures(self, ingested):
        assert ingested.raw_metrics == {"space": "MNI", "volume_mm3": 100.0}

    def test_stamps_the_review_plan(self, ingested, review_plan):
        assert ingested.review_plan_id == review_plan.pk

    def test_rerender_refreshes_the_bytes(self, rerendered):
        assert bytes(rerendered.img) == b"A"

    def test_rerender_refreshes_the_measures(self, rerendered):
        assert rerendered.raw_metrics["volume_mm3"] == 150.0

    def test_rerender_preserves_the_priority(self, rerendered):
        # priority is not in update_fields, so a re-render must not clobber it.
        assert rerendered.priority == 2.5


@pytest.mark.django_db
class TestAnnotationCreate:
    CELLS = ((1, 2, Ratings.FAIL), (3, 4, Ratings.UNSURE), (5, 6, Ratings.FAIL))

    @pytest.fixture
    def empty(self, mask_image, mask_session) -> Annotation:
        return annotation_create(
            image=mask_image,
            session=mask_session,
            grid_cols=28,
            grid_rows=21,
            cells=[],
        )

    @pytest.fixture
    def marked(self, mask_image, mask_session) -> Annotation:
        return annotation_create(
            image=mask_image,
            session=mask_session,
            grid_cols=28,
            grid_rows=21,
            cells=self.CELLS,
        )

    @pytest.fixture
    def flagged(self, mask_image, mask_session) -> Annotation:
        """A submission carrying the optional source-data flag and a comment."""
        return annotation_create(
            image=mask_image,
            session=mask_session,
            grid_cols=28,
            grid_rows=21,
            cells=[(0, 0, Ratings.FAIL)],
            source_data_issue=True,
            comments="widespread",
        )

    def test_empty_submission_is_still_an_annotation(self, empty):
        assert Annotation.objects.count() == 1

    def test_empty_submission_has_no_cells(self, empty):
        assert empty.cells.count() == 0

    def test_marked_submission_is_one_annotation(self, marked):
        assert Annotation.objects.count() == 1

    def test_marked_submission_stores_every_cell(self, marked):
        assert AnnotationCell.objects.count() == len(self.CELLS)

    def test_marked_cells_round_trip(self, marked):
        stored = sorted((c.col, c.row, c.rating) for c in marked.cells.all())

        assert stored == sorted(self.CELLS)

    def test_records_the_grid(self, flagged):
        assert (flagged.grid_cols, flagged.grid_rows) == (28, 21)

    def test_records_the_source_data_flag(self, flagged):
        assert flagged.source_data_issue is True

    def test_records_the_comments(self, flagged):
        assert flagged.comments == "widespread"

    def test_links_the_image(self, flagged, mask_image):
        assert flagged.image_id == mask_image.pk

    def test_links_the_session(self, flagged, mask_session):
        assert flagged.session_id == mask_session.pk
