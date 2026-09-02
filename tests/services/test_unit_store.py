"""Tests for services.unit_store — one unit's files + rows, stored together."""

import pytest

from django_dirt_ratings import services, storage
from django_dirt_ratings.models import (
    DisplayMode,
    Image,
    MeasuredFile,
    Rating,
    Ratings,
    Step,
)

BLOBS = {
    (int(DisplayMode.X), 0): b"x-bytes",
    (int(DisplayMode.Y), 1): b"y-bytes",
}


def _store(blobs) -> int:
    return services.unit_store(
        step=int(Step.MASK),
        file1="unit.nii.gz",
        file2=None,
        entities={"space": "MNI"},
        values={},
        review_plan_id=None,
        blobs=blobs,
    )


@pytest.fixture
def stored(db) -> int:
    return _store(BLOBS)


@pytest.fixture
def restored_identical(stored) -> list[str]:
    """The same unit stored again, byte-identical; nothing should move."""
    before = sorted(storage.stored_names())
    _store(BLOBS)
    return before


@pytest.fixture
def restored_changed(stored) -> Image:
    """The X view re-rendered with new bytes; the Y view untouched."""
    _store({**BLOBS, (int(DisplayMode.X), 0): b"x-bytes-v2"})
    return Image.objects.get(display=DisplayMode.X, slice=0)


class TestUnitStore:
    def test_creates_a_row_per_view(self, stored):
        assert Image.objects.count() == 2

    def test_stores_a_file_per_view(self, stored):
        assert len(list(storage.stored_names())) == 2

    def test_rows_point_at_their_files(self, stored):
        image = Image.objects.get(display=DisplayMode.X, slice=0)

        assert image.img.read() == b"x-bytes"

    def test_records_the_entities_on_the_measured_file(self, stored):
        entities = MeasuredFile.objects.get(file1="unit.nii.gz").entities

        assert entities == {"space": "MNI"}


class TestIdempotentRestore:
    def test_rewrites_nothing(self, restored_identical):
        assert sorted(storage.stored_names()) == restored_identical

    def test_keeps_the_row_count(self, restored_identical):
        assert Image.objects.count() == 2


class TestChangedRestore:
    def test_repoints_the_row_at_the_new_bytes(self, restored_changed):
        assert restored_changed.img.read() == b"x-bytes-v2"

    def test_deletes_the_replaced_file(self, restored_changed):
        assert len(list(storage.stored_names())) == 2

    def test_preserves_the_primary_key(self, stored):
        before = Image.objects.get(display=DisplayMode.X, slice=0).pk

        _store({**BLOBS, (int(DisplayMode.X), 0): b"x-bytes-v2"})

        assert Image.objects.get(display=DisplayMode.X, slice=0).pk == before

    def test_preserves_ratings(self, stored, fmap_session):
        image = Image.objects.get(display=DisplayMode.X, slice=0)
        services.rating_create(image=image, session=fmap_session, rating=Ratings.PASS)

        _store({**BLOBS, (int(DisplayMode.X), 0): b"x-bytes-v2"})

        assert Rating.objects.filter(image=image).count() == 1


class TestNarrowedRestore:
    """The incoming view set is authoritative: absent views are removed."""

    @pytest.fixture
    def narrowed(self, stored) -> None:
        """The unit re-stored with only its X view — the Y view is gone."""
        _store({(int(DisplayMode.X), 0): b"x-bytes"})

    def test_the_absent_view_row_is_deleted(self, narrowed):
        assert Image.objects.count() == 1

    def test_the_absent_view_file_is_deleted(self, narrowed):
        assert len(list(storage.stored_names())) == 1

    def test_the_surviving_view_is_untouched(self, narrowed):
        image = Image.objects.get()

        assert image.img.read() == b"x-bytes"

    def test_the_unit_digest_converges(self, narrowed):
        from django_dirt_ratings import selectors

        digest = selectors.unit_digests(step=int(Step.MASK))[0]["unit_digest"]

        assert digest == storage.unit_digest(
            [(int(DisplayMode.X), 0, storage.image_digest(b"x-bytes"))]
        )


class TestNullSlice:
    """The single-image DTIFIT path: NULL slice rows go through image_upsert."""

    @pytest.fixture
    def dtifit_stored(self, db) -> None:
        services.unit_store(
            step=int(Step.DTIFIT),
            file1="dwi.nii.gz",
            file2=None,
            entities=None,
            values={},
            review_plan_id=None,
            blobs={(int(DisplayMode.X), None): b"animation"},
        )

    def test_stores_the_row(self, dtifit_stored):
        assert Image.objects.filter(step=Step.DTIFIT, slice=None).count() == 1

    def test_a_restore_adds_no_duplicate(self, dtifit_stored):
        services.unit_store(
            step=int(Step.DTIFIT),
            file1="dwi.nii.gz",
            file2=None,
            entities=None,
            values={},
            review_plan_id=None,
            blobs={(int(DisplayMode.X), None): b"animation-v2"},
        )

        assert Image.objects.filter(step=Step.DTIFIT).count() == 1
