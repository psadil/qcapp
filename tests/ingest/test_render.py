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
