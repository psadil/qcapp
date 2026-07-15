"""Tests for django_dirt_ratings services."""

import pytest
from django.core.exceptions import ValidationError

from django_dirt_ratings.models import (
    Annotation,
    DisplayMode,
    Image,
    Rating,
    Ratings,
    Step,
)
from django_dirt_ratings.services import (
    annotation_bulk_create,
    image_create,
    image_delete,
    image_upsert,
    rating_create,
    session_create,
)


@pytest.mark.django_db
class TestSessionCreate:
    def test_creates_session(self):
        session = session_create(step=Step.MASK)
        assert session.pk is not None
        assert session.step == Step.MASK
        assert session.user is None

    def test_creates_session_with_user(self):
        session = session_create(step=Step.DTIFIT, user="rater1")
        assert session.user == "rater1"

    def test_invalid_step_raises(self):
        with pytest.raises(ValidationError):
            session_create(step=999)


@pytest.mark.django_db
class TestRatingCreate:
    def test_saves_instance(self, fmap_image, fmap_session):
        rating = rating_create(
            image=fmap_image, session=fmap_session, rating=Ratings.PASS
        )
        assert rating.pk is not None
        assert rating.image == fmap_image
        assert rating.session == fmap_session
        assert rating.rating == Ratings.PASS

    def test_persists_to_db(self, fmap_image, fmap_session):
        rating = rating_create(
            image=fmap_image,
            session=fmap_session,
            rating=Ratings.FAIL,
            source_data_issue=True,
        )
        saved = Rating.objects.get(pk=rating.pk)
        assert saved.rating == Ratings.FAIL
        assert saved.source_data_issue is True

    def test_invalid_rating_raises(self, fmap_image, fmap_session):
        with pytest.raises(ValidationError):
            rating_create(image=fmap_image, session=fmap_session, rating=999)
        assert Rating.objects.count() == 0


@pytest.mark.django_db
class TestImageServices:
    def test_image_create(self):
        image = image_create(
            img=b"\x89PNG",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )
        assert image.pk is not None
        assert bytes(image.img) == b"\x89PNG"

    def test_image_delete(self, mask_image):
        pk = mask_image.pk
        image_delete(image=mask_image)
        assert not Image.objects.filter(pk=pk).exists()

    def test_image_upsert_creates_then_updates_in_place(self):
        created = image_upsert(
            img=b"first",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )
        updated = image_upsert(
            img=b"second",
            file1="a.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
            slice=0,
        )
        # Same identity -> same row refreshed, not a duplicate.
        assert updated.pk == created.pk
        assert Image.objects.count() == 1
        assert bytes(Image.objects.get().img) == b"second"


@pytest.mark.django_db
class TestAnnotationBulkCreate:
    def test_no_points_saves_single_row(self, mask_image, mask_session):
        created = annotation_bulk_create(
            image=mask_image, session=mask_session, points=[]
        )
        assert len(created) == 1
        assert Annotation.objects.count() == 1
        assert Annotation.objects.get().geometry is None

    def test_multiple_points_bulk_creates(self, mask_image, mask_session):
        points = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]

        annotation_bulk_create(image=mask_image, session=mask_session, points=points)

        assert Annotation.objects.count() == 3
        stored = sorted(
            (annotation.geometry.x, annotation.geometry.y)
            for annotation in Annotation.objects.all()
        )
        assert stored == points

    def test_bulk_created_share_image_and_session(self, mask_image, mask_session):
        annotation_bulk_create(
            image=mask_image,
            session=mask_session,
            points=[(10.0, 20.0), (30.0, 40.0)],
            comments="two clicks",
        )
        for annotation in Annotation.objects.all():
            assert annotation.image_id == mask_image.pk
            assert annotation.session_id == mask_session.pk
            assert annotation.comments == "two clicks"
