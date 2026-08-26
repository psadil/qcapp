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
# The "true" warp between the fake canonical and target spaces: a world-x
# translation of exactly two voxels.
SHIFT_MM = 8.0
SHIFT_VOX = int(SHIFT_MM / 4.0)


def _ball_at(center_mm, radius_mm):
    """A boolean ball on the synthetic grid, placed by world coordinates."""
    ijk = np.indices(SHAPE).reshape(3, -1).T
    world = affines.apply_affine(AFFINE, ijk)
    dist = np.linalg.norm(world - np.asarray(center_mm), axis=1)
    return (dist <= radius_mm).reshape(SHAPE)


def _radial_t1w(center_mm):
    """A radial-cone "T1w" centered at ``center_mm``.

    Non-constant within any brain mask, so the correlation gate in
    ``_warp_labels`` discriminates aligned from misaligned placements.
    """
    ijk = np.indices(SHAPE).reshape(3, -1).T
    world = affines.apply_affine(AFFINE, ijk)
    dist = np.linalg.norm(world - np.asarray(center_mm), axis=1).reshape(SHAPE)
    return nb.nifti1.Nifti1Image(
        np.maximum(0.0, 60.0 - dist).astype(np.float32), AFFINE
    )


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
    t1w = _radial_t1w((0.0, -18.0, 5.0))
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


@pytest.fixture(scope="module")
def target_templates(tmp_path_factory):
    """T1w/mask/atlas for the fake target space: canonical anatomy at +SHIFT_MM x."""
    tmp = tmp_path_factory.mktemp("target-templates")
    mask = _ball_at((SHIFT_MM, -18.0, 5.0), 55.0)
    atlas = np.zeros(SHAPE, dtype=np.uint8)
    for name, index in rois._HOSPA_STRUCTURES.items():
        sign = -1 if name.startswith("left") else 1
        center = (
            (sign * 18.0 + SHIFT_MM, -5.0, 18.0)
            if "ventricle" in name
            else (sign * 28.0 + SHIFT_MM, -22.0, -15.0)
        )
        atlas[_ball_at(center, 10.0)] = index
    paths = {}
    images = {
        "T1w": _radial_t1w((SHIFT_MM, -18.0, 5.0)),
        "mask": nb.nifti1.Nifti1Image(mask.astype(np.uint8), AFFINE),
        "dseg": nb.nifti1.Nifti1Image(atlas, AFFINE),
    }
    for name, img in images.items():
        paths[name] = tmp / f"target_{name}.nii.gz"
        img.to_filename(paths[name])
    return paths


@pytest.fixture
def warped_build_env(monkeypatch, synthetic_templates, target_templates):
    """Wire a non-canonical build: stub transform + a known-shift applier."""
    canon_paths, landmark_path = synthetic_templates
    requests = []

    def fake_tf_get(space, cohort, **query):
        paths = canon_paths if space == rois.CANONICAL_SPACE else target_templates
        return paths[query["suffix"]]

    def fake_ensure_xfm(space, cohort, cache_dir):
        requests.append((space, cohort, cache_dir))
        h5_path, meta_path = rois._xfm_paths(space, cohort, cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        h5_path.write_bytes(b"not a real transform")  # only _sha256 reads it
        meta_path.write_text(
            json.dumps({"engine": "stub", "xfm_version": rois.XFM_VERSION})
        )
        return h5_path

    def fake_apply_xfm(xfm_path, moving_img, reference_img, order):
        return np.roll(np.asarray(moving_img.dataobj), SHIFT_VOX, axis=0)

    monkeypatch.setattr(rois, "_tf_get", fake_tf_get)
    monkeypatch.setattr(rois, "_ensure_xfm", fake_ensure_xfm)
    monkeypatch.setattr(rois, "_apply_xfm", fake_apply_xfm)
    monkeypatch.setattr(rois.datasets, "get_landmarks", lambda: landmark_path)
    return requests


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


def test_warped_build_requests_the_transform_for_the_target_space(
    warped_build_env, tmp_path
):
    rois.build_rois("MNI152NLin6Asym", None, tmp_path)

    assert warped_build_env == [("MNI152NLin6Asym", None, tmp_path)]


def test_warped_build_places_the_landmark_on_the_target_grid(
    warped_build_env, tmp_path
):
    artifact = rois.build_rois("MNI152NLin6Asym", None, tmp_path)

    data = np.asarray(rois._load(artifact.dseg).dataobj)
    com = affines.apply_affine(
        AFFINE, ndimage.center_of_mass(data == rois.LABELS["left_central_sulcus"])
    )
    assert np.allclose(com, (30.0 + SHIFT_MM, -25.0, 40.0), atol=4.0)


def test_warped_build_records_the_xfm_sha256(warped_build_env, tmp_path):
    artifact = rois.build_rois("MNI152NLin6Asym", None, tmp_path)

    meta = json.loads(artifact.meta.read_text())
    h5_path, _ = rois._xfm_paths("MNI152NLin6Asym", None, tmp_path)
    assert meta["structures"]["left_central_sulcus"]["registration"]["xfm"] == {
        h5_path.name: rois._sha256(h5_path)
    }


def test_warp_gate_rejects_a_transform_that_degrades_alignment(
    warped_build_env, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        rois,
        "_apply_xfm",
        lambda xfm_path, moving_img, reference_img, order: np.roll(
            np.asarray(moving_img.dataobj), -SHIFT_VOX, axis=0
        ),
    )

    with pytest.raises(rois.RoiUnavailableError):
        rois.build_rois("MNI152NLin6Asym", None, tmp_path)


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
