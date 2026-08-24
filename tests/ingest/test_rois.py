"""Tests for per-space landmark ROI generation (offline; synthetic templates)."""

import json

import nibabel as nb
import numpy as np
import pytest
from nibabel import affines
from scipy import ndimage

from django_dirt_ratings.management.ingest import rois

SHAPE = (40, 48, 40)
AFFINE = np.array(
    [
        [4.0, 0, 0, -78.0],
        [0, 4.0, 0, -96.0],
        [0, 0, 4.0, -70.0],
        [0, 0, 0, 1.0],
    ]
)


def _ball_at(center_mm, radius_mm):
    """A boolean ball on the synthetic grid, placed by world coordinates."""
    ijk = np.indices(SHAPE).reshape(3, -1).T
    world = affines.apply_affine(AFFINE, ijk)
    dist = np.linalg.norm(world - np.asarray(center_mm), axis=1)
    return (dist <= radius_mm).reshape(SHAPE)


@pytest.fixture(scope="module")
def brain_mask():
    return _ball_at((0.0, -18.0, 5.0), 55.0)


@pytest.fixture(scope="module")
def atlas_img():
    """A synthetic HOSPA-like atlas with structures at plausible positions."""
    data = np.zeros(SHAPE, dtype=np.uint8)
    for name, index in rois._HOSPA_STRUCTURES.items():
        # RAS: anatomical left is negative x.
        sign = -1 if name.startswith("left") else 1
        center = (
            (sign * 18.0, -5.0, 18.0)
            if "ventricle" in name
            else (sign * 28.0, -22.0, -15.0)
        )
        data[_ball_at(center, 10.0)] = index
    return nb.nifti1.Nifti1Image(data, AFFINE)


@pytest.fixture(scope="module")
def synthetic_templates(tmp_path_factory, brain_mask, atlas_img):
    """On-disk T1w/mask/atlas + canonical landmark dseg, all on one grid."""
    tmp = tmp_path_factory.mktemp("templates")
    t1w = nb.nifti1.Nifti1Image((brain_mask * 100.0).astype(np.float32), AFFINE)
    mask_img = nb.nifti1.Nifti1Image(brain_mask.astype(np.uint8), AFFINE)
    paths = {}
    for name, img in {"T1w": t1w, "mask": mask_img, "dseg": atlas_img}.items():
        paths[name] = tmp / f"{name}.nii.gz"
        img.to_filename(paths[name])

    landmarks = np.zeros(SHAPE, dtype=np.uint8)
    label = rois.LABELS["left_central_sulcus"]
    landmarks[_ball_at((30.0, -25.0, 40.0), 8.0)] = label
    landmark_path = tmp / "tpl-canonical_desc-landmarks_dseg.nii.gz"
    nb.nifti1.Nifti1Image(landmarks, AFFINE).to_filename(landmark_path)
    (tmp / "tpl-canonical_desc-landmarks_dseg.json").write_text(
        json.dumps({"labels": {"left_central_sulcus": label}})
    )
    return paths, landmark_path


@pytest.fixture
def offline_build(monkeypatch, synthetic_templates, tmp_path):
    """build_rois wired to the synthetic assets; returns the built artifact."""
    paths, landmark_path = synthetic_templates

    def fake_tf_get(space, cohort, **query):
        return paths[query["suffix"]]

    monkeypatch.setattr(rois, "_tf_get", fake_tf_get)
    monkeypatch.setattr(rois.datasets, "get_landmarks", lambda: landmark_path)
    return rois.build_rois("MNI152NLin2009cAsym", None, tmp_path)


# --------------------------------------------------------------------------- #
# Morphology helpers
# --------------------------------------------------------------------------- #
def test_brain_band_is_one_connected_shell(brain_mask):
    band = rois._brain_band(brain_mask, (4.0, 4.0, 4.0), rois.BAND_MM)

    assert ndimage.label(band)[1] == 1


def test_brain_band_straddles_the_mask_boundary(brain_mask):
    band = rois._brain_band(brain_mask, (4.0, 4.0, 4.0), rois.BAND_MM)

    surface = brain_mask ^ ndimage.binary_erosion(brain_mask)
    assert (band & surface).sum() == surface.sum()


def test_ellipsoid_radius_scales_with_zooms():
    fine, coarse = (
        rois._ellipsoid(4.0, (1.0, 1.0, 1.0)),
        rois._ellipsoid(4.0, (2.0, 2.0, 2.0)),
    )

    assert (fine.shape[0], coarse.shape[0]) == (9, 5)


def test_cleanup_warped_removes_stray_fragment():
    arr = _ball_at((30.0, -25.0, 40.0), 10.0).copy()
    arr[0, 0, 0] = True  # a chipped-off warp speck

    cleaned, _ = rois._cleanup_warped(arr, "test_structure")

    assert ndimage.label(cleaned)[1] == 1


def test_cleanup_warped_rejects_gross_change():
    two_equal_blobs = _ball_at((30.0, -25.0, 40.0), 10.0) | _ball_at(
        (-30.0, -25.0, 40.0), 10.0
    )

    with pytest.raises(rois.RoiUnavailableError):
        rois._cleanup_warped(two_equal_blobs, "test_structure")


# --------------------------------------------------------------------------- #
# Atlas extraction
# --------------------------------------------------------------------------- #
def test_atlas_structures_extracts_every_requested_structure(atlas_img, brain_mask):
    mask_img = nb.nifti1.Nifti1Image(brain_mask.astype(np.uint8), AFFINE)

    out = rois._atlas_structures(atlas_img, mask_img)

    assert set(out) == set(rois._HOSPA_STRUCTURES)


def test_atlas_structures_rejects_swapped_hemispheres(atlas_img, brain_mask):
    swapped = np.asarray(atlas_img.dataobj)[::-1]  # mirror x: left labels on the right
    mask_img = nb.nifti1.Nifti1Image(brain_mask.astype(np.uint8), AFFINE)

    with pytest.raises(rois.RoiUnavailableError):
        rois._atlas_structures(nb.nifti1.Nifti1Image(swapped, AFFINE), mask_img)


# --------------------------------------------------------------------------- #
# build_rois / ensure_rois
# --------------------------------------------------------------------------- #
def test_unknown_space_raises_unavailable(tmp_path):
    with pytest.raises(rois.RoiUnavailableError):
        rois.build_rois("NotASpace", None, tmp_path)


def test_unknown_space_never_touches_templateflow(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(rois, "_tf_get", lambda *a, **k: calls.append(a))

    with pytest.raises(rois.RoiUnavailableError):
        rois.build_rois("NotASpace", None, tmp_path)
    assert calls == []


def test_build_writes_the_labeled_dseg(offline_build):
    data = np.asarray(rois._load(offline_build.dseg).dataobj)

    assert set(np.unique(data)) > {0, rois.LABELS["brain_band"]}


def test_build_sidecar_records_three_cuts_per_axis(offline_build):
    cuts = rois.load_cuts(offline_build.meta)

    assert {axis: len(coords) for axis, coords in cuts.items()} == {
        "x": rois.N_CUTS,
        "y": rois.N_CUTS,
        "z": rois.N_CUTS,
    }


def test_build_sidecar_records_per_structure_provenance(offline_build):
    meta = json.loads(offline_build.meta.read_text())

    assert meta["structures"]["brain_band"]["source"] == "procedural"


def test_cuts_stay_inside_the_brain_bbox(offline_build):
    cuts = rois.load_cuts(offline_build.meta)

    assert all(-96.0 <= c <= 96.0 for coords in cuts.values() for c in coords)


def test_ensure_rois_reuses_the_cached_artifact(
    monkeypatch, synthetic_templates, tmp_path
):
    paths, landmark_path = synthetic_templates
    monkeypatch.setattr(
        rois, "_tf_get", lambda space, cohort, **query: paths[query["suffix"]]
    )
    monkeypatch.setattr(rois.datasets, "get_landmarks", lambda: landmark_path)
    first = rois.ensure_rois("MNI152NLin2009cAsym", cache_dir=tmp_path)
    mtime = first.dseg.stat().st_mtime_ns

    second = rois.ensure_rois("MNI152NLin2009cAsym", cache_dir=tmp_path)

    assert second.dseg.stat().st_mtime_ns == mtime
