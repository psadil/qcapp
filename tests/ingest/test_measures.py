"""Tests for computed metric extractors (require the neuro stack)."""

import pytest

np = pytest.importorskip("numpy")
nb = pytest.importorskip("nibabel")


def test_mask_volume_is_mm3(tmp_path):
    from django_dirt_ratings.management.ingest.measures import MaskVolume

    # 2 mm isotropic voxels (8 mm^3 each); 8 nonzero voxels → 64 mm^3.
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[:2, :2, :2] = 1
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)

    assert MaskVolume().extract({"mask": str(path)}) == pytest.approx(64.0)


def test_registered_under_key():
    from django_dirt_ratings.management.ingest.measures import (
        MaskVolume,
        MetricExtractor,
    )

    assert isinstance(MetricExtractor.get("mask_volume"), MaskVolume)
