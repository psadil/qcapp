"""Tests for computed metric extractors (require the neuro stack)."""

from typing import NamedTuple

import pytest

np = pytest.importorskip("numpy")
nb = pytest.importorskip("nibabel")
measures = pytest.importorskip("django_dirt_ratings.management.ingest.measures")


class _CubeMask(NamedTuple):
    """A written-out mask plus the reference image transforms are defined against."""

    path: str
    reference: object


@pytest.fixture
def cube_mask(tmp_path) -> _CubeMask:
    """A 20 mm cube brain mask at 1 mm iso, centroid offset from the origin."""
    data = np.zeros((40, 40, 40), np.uint8)
    data[10:30, 10:30, 10:30] = 1
    affine = np.eye(4)
    affine[:3, 3] = [-20, -20, -20]
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)
    return _CubeMask(path=str(path), reference=nb.Nifti1Image(data, affine))


@pytest.fixture
def write_itk_affine(tmp_path):
    """Write a 4x4 matrix as an ITK transform file; hand back its path."""
    nt = pytest.importorskip("nitransforms")

    def _write(matrix, reference) -> str:
        path = tmp_path / "xfm.txt"
        nt.linear.Affine(matrix, reference=reference).to_filename(path, fmt="itk")
        return str(path)

    return _write


def test_mask_volume_is_mm3(tmp_path):
    # 2 mm isotropic voxels (8 mm^3 each); 8 nonzero voxels → 64 mm^3.
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[:2, :2, :2] = 1
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)

    volume = measures.MaskVolume().extract({"mask": str(path)})

    assert volume == pytest.approx(64.0)


def test_identity_transform_displaces_nothing(cube_mask, write_itk_affine):
    xfm = write_itk_affine(np.eye(4), cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement == pytest.approx(0.0)


def test_pure_translation_displaces_by_its_own_length(cube_mask, write_itk_affine):
    """A = 0 for a pure translation, so the radius/centroid terms drop out."""
    matrix = np.eye(4)
    matrix[0, 3] = 5.0
    xfm = write_itk_affine(matrix, cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement == pytest.approx(5.0)


def test_small_rotation_is_a_small_positive_displacement(cube_mask, write_itk_affine):
    theta = np.deg2rad(2)
    matrix = np.eye(4)
    matrix[:2, :2] = [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    xfm = write_itk_affine(matrix, cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement is not None and displacement > 0


@pytest.mark.parametrize(
    "key, expected_class",
    [
        ("mask_volume", measures.MaskVolume),
        ("affine_displacement", measures.AffineDisplacement),
    ],
)
def test_registered_under_key(key, expected_class):
    extractor = measures.MetricExtractor.get(key)

    assert isinstance(extractor, expected_class)
