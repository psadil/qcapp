"""Tests for the media-storage layout (django_dirt_ratings.storage)."""

from typing import Any

import pytest
from django.core.files.storage import default_storage

from django_dirt_ratings import storage
from django_dirt_ratings.models import Step


class TestImageDigest:
    def test_is_sixteen_hex_characters(self):
        assert len(storage.image_digest(b"payload")) == 16

    def test_is_stable_for_identical_bytes(self):
        assert storage.image_digest(b"payload") == storage.image_digest(b"payload")

    def test_differs_for_different_bytes(self):
        assert storage.image_digest(b"one") != storage.image_digest(b"two")


class TestUnitKey:
    def test_keeps_the_basename_readable(self):
        assert storage.unit_key("sub-01_mask.nii.gz").startswith("sub-01_mask.nii.gz-")

    def test_a_path_yields_no_directory_separators(self):
        assert "/" not in storage.unit_key("freesurfer/sub-01/mri/ribbon.mgz")

    def test_distinct_paths_with_one_basename_get_distinct_keys(self):
        keys = {
            storage.unit_key("freesurfer/sub-01/mri/ribbon.mgz"),
            storage.unit_key("freesurfer/sub-02/mri/ribbon.mgz"),
        }

        assert len(keys) == 2


class TestImageName:
    def test_layout_carries_step_unit_digest_and_view(self):
        name = storage.image_name(
            step=Step.MASK, file1="a.nii.gz", display=1, slice=3, digest="d" * 16
        )

        assert (
            name == f"images/masks/{storage.unit_key('a.nii.gz')}/{'d' * 16}-d1s3.avif"
        )

    def test_a_null_slice_omits_the_cut(self):
        name = storage.image_name(
            step=Step.DTIFIT, file1="a.nii.gz", display=0, slice=None, digest="d" * 16
        )

        assert name.endswith(f"{'d' * 16}-d0.avif")


class TestSave:
    def test_replaces_rather_than_renaming(self):
        storage.save("images/masks/u/x-d0s0.avif", b"old")

        storage.save("images/masks/u/x-d0s0.avif", b"new")

        assert default_storage.open("images/masks/u/x-d0s0.avif").read() == b"new"

    def test_stores_exactly_one_file(self):
        storage.save("images/masks/u/x-d0s0.avif", b"old")
        storage.save("images/masks/u/x-d0s0.avif", b"new")

        assert list(storage.stored_names()) == ["images/masks/u/x-d0s0.avif"]


class TestDelete:
    def test_removes_the_file(self):
        storage.save("images/masks/u/x-d0s0.avif", b"data")

        storage.delete("images/masks/u/x-d0s0.avif")

        assert list(storage.stored_names()) == []


class TestUnitDigest:
    def test_is_order_independent(self):
        images = [(0, 1, "a" * 16), (1, None, "b" * 16), (2, 3, "c" * 16)]

        assert storage.unit_digest(images) == storage.unit_digest(reversed(images))

    def test_differs_when_one_image_changes(self):
        before = [(0, 1, "a" * 16), (1, 2, "b" * 16)]
        after = [(0, 1, "a" * 16), (1, 2, "x" * 16)]

        assert storage.unit_digest(before) != storage.unit_digest(after)

    def test_a_null_slice_never_aliases_an_integer_one(self):
        sliceless = [(0, None, "a" * 16)]
        negative = [(0, -1, "a" * 16)]

        assert storage.unit_digest(sliceless) != storage.unit_digest(negative)


def _meta(**overrides: Any) -> str:
    """The meta digest of one reference unit, overriding any field."""
    base: dict[str, Any] = {
        "file2": "ref.nii.gz",
        "entities": {"space": "MNI", "res": "2"},
        "values": {"mask_volume": 100.0, "fov_cutoff_max": 0.5},
        "plan_hash": "h" * 16,
    }
    return storage.unit_meta_digest(**(base | overrides))


class TestUnitMetaDigest:
    def test_is_stable_for_identical_metadata(self):
        assert _meta() == _meta()

    def test_key_order_does_not_matter(self):
        reordered = _meta(
            entities={"res": "2", "space": "MNI"},
            values={"fov_cutoff_max": 0.5, "mask_volume": 100.0},
        )

        assert _meta() == reordered

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param({"values": {"mask_volume": 150.0}}, id="metric-value"),
            pytest.param(
                {"values": {"mask_volume": 100.0, "new": None}}, id="metric-added"
            ),
            pytest.param({"entities": {"space": "native"}}, id="entities"),
            pytest.param({"plan_hash": None}, id="plan"),
            pytest.param({"file2": None}, id="file2"),
        ],
    )
    def test_any_metadata_change_changes_the_digest(self, change):
        assert _meta() != _meta(**change)


@pytest.fixture
def nested(tmp_path):
    """Two stored images in different unit directories."""
    storage.save("images/masks/u1/a-d0s0.avif", b"1")
    storage.save("images/dtifit/u2/b-d0.avif", b"2")


class TestStoredNames:
    def test_walks_every_directory(self, nested):
        assert sorted(storage.stored_names()) == [
            "images/dtifit/u2/b-d0.avif",
            "images/masks/u1/a-d0s0.avif",
        ]

    def test_an_empty_store_yields_nothing(self):
        assert list(storage.stored_names()) == []
