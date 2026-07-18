"""Tests for computed metric extractors (require the neuro stack)."""

import pytest

np = pytest.importorskip("numpy")
nb = pytest.importorskip("nibabel")


def _cube_mask(tmp_path):
    """A 20 mm cube brain mask at 1 mm iso, centroid offset from the origin."""
    data = np.zeros((40, 40, 40), np.uint8)
    data[10:30, 10:30, 10:30] = 1
    affine = np.eye(4)
    affine[:3, 3] = [-20, -20, -20]
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)
    return data, affine, path


def _itk_affine(tmp_path, matrix, reference):
    nt = pytest.importorskip("nitransforms")
    path = tmp_path / "xfm.txt"
    nt.linear.Affine(matrix, reference=reference).to_filename(path, fmt="itk")
    return path


def test_mask_volume_is_mm3(tmp_path):
    from django_dirt_ratings.management.ingest.measures import MaskVolume

    # 2 mm isotropic voxels (8 mm^3 each); 8 nonzero voxels → 64 mm^3.
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[:2, :2, :2] = 1
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)

    assert MaskVolume().extract({"mask": str(path)}) == pytest.approx(64.0)


def test_affine_displacement_is_rms_mm(tmp_path):
    from django_dirt_ratings.management.ingest.measures import AffineDisplacement

    data, affine, mask = _cube_mask(tmp_path)
    ref = nb.Nifti1Image(data, affine)
    ext = AffineDisplacement()

    # Identity transform moves nothing.
    ident = _itk_affine(tmp_path, np.eye(4), ref)
    assert ext.extract({"mask": str(mask), "transform": str(ident)}) == pytest.approx(
        0.0
    )

    # A pure 5 mm translation displaces the brain by exactly 5 mm (A = 0, so the
    # radius/centroid drop out).
    trans = np.eye(4)
    trans[0, 3] = 5.0
    xfm = _itk_affine(tmp_path, trans, ref)
    assert ext.extract({"mask": str(mask), "transform": str(xfm)}) == pytest.approx(5.0)

    # A small rotation is a small positive displacement.
    theta = np.deg2rad(2)
    rot = np.eye(4)
    rot[:2, :2] = [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    xfm = _itk_affine(tmp_path, rot, ref)
    assert ext.extract({"mask": str(mask), "transform": str(xfm)}) > 0


def test_registered_under_key():
    from django_dirt_ratings.management.ingest.measures import (
        AffineDisplacement,
        MaskVolume,
        MetricExtractor,
    )

    assert isinstance(MetricExtractor.get("mask_volume"), MaskVolume)
    assert isinstance(MetricExtractor.get("affine_displacement"), AffineDisplacement)
