"""Tests for the rendering seams that can regress silently (neuro stack; dev env)."""

import io

import numpy as np
import pytest
from matplotlib import pyplot as plt
from PIL import Image, ImageSequence

from django_dirt_ratings.management.ingest import render
from django_dirt_ratings.models import DisplayMode


@pytest.fixture
def figure():
    f = plt.figure(figsize=(1.6, 1.2), layout="none")
    plt.imshow(np.linspace(0, 1, 64 * 48).reshape(48, 64), cmap="gray")
    yield f
    plt.close(f)


def test_avif_kwargs_are_consumed(figure):
    """Pillow drops unknown save kwargs silently — the old ``lossless=True`` was
    a no-op for years. Encoding with our kwargs must actually change the bytes."""
    default = io.BytesIO()
    figure.savefig(default, format="avif")

    tuned = io.BytesIO()
    figure.savefig(tuned, format="avif", pil_kwargs=dict(render._AVIF_KWARGS))

    assert tuned.getvalue() != default.getvalue()


@pytest.fixture(scope="module")
def synthetic_grid():
    """The coarse 4 mm grid every synthetic normalization volume is built on.

    Returns the shape, the affine, and each voxel's distance in mm from the
    centre — enough to carve a ball of brain or a shell of landmark out of it.
    """
    shape = (32, 32, 32)
    affine = np.diag([4.0, 4.0, 4.0, 1.0])
    affine[:3, 3] = (-64.0, -64.0, -64.0)
    grid = np.indices(shape)
    center = np.array(shape) // 2
    dist = np.sqrt((((grid - center[:, None, None, None]) * 4.0) ** 2).sum(0))
    return shape, affine, dist


@pytest.fixture(scope="module")
def spatial_normalization_inputs(tmp_path_factory, synthetic_grid):
    """Tiny synthetic volumes for one spatial-normalization job.

    A uniform ball of brain inside a landmark shell.
    """
    import json

    import nibabel as nb

    from django_dirt_ratings.management.ingest import rois

    shape, affine, dist = synthetic_grid
    tmp = tmp_path_factory.mktemp("spatial_normalization")

    mask = (dist <= 40.0).astype(np.uint8)
    anat = np.full(shape, 1000.0, dtype=np.float32)
    dseg = np.zeros(shape, dtype=np.uint8)
    dseg[(dist > 30.0) & (dist <= 38.0)] = rois.LABELS["brain_band"]

    inputs = {}
    for role, img in {
        "anat": nb.nifti1.Nifti1Image(anat, affine),
        "mask": nb.nifti1.Nifti1Image(mask, affine),
        "rois": nb.nifti1.Nifti1Image(dseg, affine),
    }.items():
        path = tmp / f"{role}.nii.gz"
        img.to_filename(path)
        inputs[role] = str(path)
    meta = tmp / "rois.json"
    meta.write_text(json.dumps({"cuts": {axis: [-20.0, 0.0, 20.0] for axis in "xyz"}}))
    inputs["roi_meta"] = str(meta)
    return inputs


@pytest.fixture(scope="module")
def spatial_normalization_blobs(spatial_normalization_inputs):
    """One rendered spatial-normalization job over those volumes."""
    return render.render_spatial_normalization(
        inputs=spatial_normalization_inputs, cuts=[0, 1, 2], displays_=list(DisplayMode)
    )


def test_spatial_normalization_renders_every_display_and_cut(
    spatial_normalization_blobs,
):
    assert set(spatial_normalization_blobs) == {
        (display, cut) for display in DisplayMode for cut in (0, 1, 2)
    }


def test_spatial_normalization_blob_decodes_as_avif(spatial_normalization_blobs):
    image = Image.open(io.BytesIO(spatial_normalization_blobs[(DisplayMode.Z, 1)]))

    assert image.format == "AVIF"


@pytest.fixture(scope="module")
def frames_for_two_brain_sizes(spatial_normalization_inputs, synthetic_grid):
    """The figure frame for a brain inside the landmarks, and one far outside."""
    import nibabel as nb
    from nilearn import image as nl_image

    roi_path = spatial_normalization_inputs["rois"]
    shape, affine, dist = synthetic_grid

    frames = []
    for radius in (40.0, 62.0):  # the landmark shell ends at 38 mm
        mask = nb.nifti1.Nifti1Image((dist <= radius).astype(np.uint8), affine)
        anat = nb.nifti1.Nifti1Image(np.full(shape, 1000.0, dtype=np.float32), affine)
        figure, slicer = render.spatial_normalization_figure(
            nl_image.reorder_img(
                render._skull_strip(anat, mask), resample="continuous"
            ),
            render._roi_img(roi_path),
            0.0,
            DisplayMode.Z,
            render._roi_bounds(roi_path)["z"],
        )
        ax = next(iter(slicer.axes.values())).ax
        frames.append((ax.get_xlim(), ax.get_ylim()))
        plt.close(figure)
    return frames


def test_a_brain_outside_the_landmarks_does_not_widen_the_frame(
    frames_for_two_brain_sizes,
):
    """nilearn frames a figure from everything drawn on it, so a failed
    normalization used to zoom the figure out around its own error — shrinking
    the misalignment on screen, and breaking the correspondence with the
    template reference shown beside it."""
    fitting, escaping = frames_for_two_brain_sizes

    assert escaping == fitting


def test_skull_strip_zeroes_everything_outside_the_mask():
    """Regression guard for the halo: un-stripped background used to render as
    a rim of non-black pixels around the brain."""
    import nibabel as nb

    anat = nb.nifti1.Nifti1Image(
        np.full((8, 8, 8), 1000.0, dtype=np.float32), np.eye(4)
    )
    mask_data = np.zeros((8, 8, 8), dtype=np.uint8)
    mask_data[2:6, 2:6, 2:6] = 1
    mask = nb.nifti1.Nifti1Image(mask_data, np.eye(4))

    stripped = render._skull_strip(anat, mask)

    assert np.asarray(stripped.dataobj)[mask_data == 0].max() == 0.0


@pytest.fixture(scope="module")
def coregistration_inputs(tmp_path_factory):
    """Tiny synthetic volumes for a coregistration job, plus an identity affine.

    An identity transform is the honest fixture: the renderer's job is to resample
    the moving image onto the reference grid, and with the two grids differing
    (2 mm boldref, 1 mm anat) that resampling still has to happen.
    """
    import nibabel as nb
    import nitransforms as nt

    tmp = tmp_path_factory.mktemp("coregistration")

    def ball(shape, zoom):
        affine = np.diag([zoom, zoom, zoom, 1.0])
        affine[:3, 3] = -0.5 * zoom * np.asarray(shape)
        centre = np.asarray(shape) / 2.0
        dist = np.sqrt(
            (((np.indices(shape) - centre[:, None, None, None]) * zoom) ** 2).sum(0)
        )
        return affine, dist

    moving_affine, moving_dist = ball((24, 24, 24), 2.0)
    ref_affine, _ = ball((48, 48, 48), 1.0)

    inputs = {}
    for role, data, affine in (
        ("boldref", (moving_dist <= 18.0) * 800.0, moving_affine),
        ("mask", (moving_dist <= 18.0).astype(np.uint8), moving_affine),
        ("epi", np.full((48, 48, 48), 500.0), ref_affine),
        ("anat", np.full((48, 48, 48), 1000.0), ref_affine),
    ):
        path = tmp / f"{role}.nii.gz"
        nb.nifti1.Nifti1Image(data.astype(np.float32), affine).to_filename(path)
        inputs[role] = str(path)

    transform = tmp / "identity_xfm.txt"
    nt.linear.Affine(np.eye(4)).to_filename(transform, fmt="itk")
    inputs["transform"] = str(transform)
    return inputs


@pytest.fixture(scope="module")
def t1w_coregistration_blobs(coregistration_inputs):
    """One rendered T1w-coregistration job, at the cut count its spec declares."""
    return render.render_t1w_coregistration(
        inputs=coregistration_inputs,
        cuts=list(range(render.COREG_N_CUTS)),
        displays_=list(DisplayMode),
    )


def test_coregistration_renders_three_cuts_per_axis(t1w_coregistration_blobs):
    """The spec declares the cut count and the renderer spaces to it; reading a
    second constant instead would silently render the first three cuts of five."""
    assert set(t1w_coregistration_blobs) == {
        (display, cut) for display in DisplayMode for cut in (0, 1, 2)
    }


def test_coregistration_blob_is_a_two_frame_animation(t1w_coregistration_blobs):
    animation = Image.open(io.BytesIO(t1w_coregistration_blobs[(DisplayMode.Z, 1)]))

    assert sum(1 for _ in ImageSequence.Iterator(animation)) == 2


def test_the_two_coregistration_steps_differ_only_in_their_reference(
    coregistration_inputs, t1w_coregistration_blobs
):
    """Same moving image, same transform, different reference volume — so the
    frames must differ. Equal bytes would mean a role name was ignored."""
    fmap = render.render_fmap_coregistration(
        inputs=coregistration_inputs,
        cuts=list(range(render.COREG_N_CUTS)),
        displays_=[DisplayMode.Z],
    )

    assert fmap[(DisplayMode.Z, 1)] != t1w_coregistration_blobs[(DisplayMode.Z, 1)]


@pytest.fixture(scope="module")
def dtifit_blobs(tmp_path_factory):
    """One rendered DTI-fit job over tiny synthetic eigenvector volumes."""
    import nibabel as nb

    rng = np.random.default_rng(0)
    shape = (16, 16, 16)
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    tmp = tmp_path_factory.mktemp("dtifit")

    inputs = {}
    fa = np.clip(rng.random(shape, dtype=np.float32), 0.1, 1.0)
    for role, data in {
        "fa": fa,
        "v1": rng.standard_normal((*shape, 3)).astype(np.float32),
        "v2": rng.standard_normal((*shape, 3)).astype(np.float32),
        "v3": rng.standard_normal((*shape, 3)).astype(np.float32),
    }.items():
        path = tmp / f"{role}.nii.gz"
        nb.nifti1.Nifti1Image(data, affine).to_filename(path)
        inputs[role] = str(path)

    return render.render_dtifit(inputs=inputs, cuts=[None], displays_=[DisplayMode.Z])


def test_dtifit_renders_one_z_blob(dtifit_blobs):
    assert set(dtifit_blobs) == {(DisplayMode.Z, None)}


def test_dtifit_blob_is_a_palindrome_animation(dtifit_blobs):
    animation = Image.open(io.BytesIO(dtifit_blobs[(DisplayMode.Z, None)]))

    # 20 slices forward + 17 back (endpoints unrepeated) = 37 frames.
    assert sum(1 for _ in ImageSequence.Iterator(animation)) == 37
