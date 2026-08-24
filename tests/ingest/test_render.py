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
def spatial_normalization_blobs(tmp_path_factory):
    """One rendered spatial-normalization job over tiny synthetic volumes."""
    import json

    import nibabel as nb

    from django_dirt_ratings.management.ingest import rois

    shape = (32, 32, 32)
    affine = np.diag([4.0, 4.0, 4.0, 1.0])
    affine[:3, 3] = (-64.0, -64.0, -64.0)
    tmp = tmp_path_factory.mktemp("spatial_normalization")

    center = np.array(shape) // 2
    grid = np.indices(shape)
    dist = np.sqrt((((grid - center[:, None, None, None]) * 4.0) ** 2).sum(0))
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

    return render.render_spatial_normalization(
        inputs=inputs, cuts=[0, 1, 2], displays_=list(DisplayMode)
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
