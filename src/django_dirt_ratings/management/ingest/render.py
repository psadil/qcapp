"""Pure rendering: derivative inputs -> QC image bytes.

Moved from ``management/commands/_render.py`` and refactored to a **prep-once**
contract. Each ``render_*`` function loads its inputs and computes every
volume-wide quantity (cut planes, intensity quantiles, derived surfaces, the
resampling transform, the template) **once**, then emits every ``(display, cut)``
blob — instead of the old per-cut functions that recomputed all of that on each
of the 3x5 calls.

Renderers take ``inputs`` (role -> location string, loaded via :mod:`loading`)
so they can run in a ``ProcessPoolExecutor`` worker with only paths crossing the
process boundary. ``RENDERERS`` maps a ``RenderJob.render_key`` to its function.
"""

from __future__ import annotations

import functools
import io
from collections.abc import Sequence

import imageio.v3 as iio
import nibabel as nb
import numpy as np
import numpy.typing as npt
from dipy.reconst import dti
from matplotlib import pyplot as plt
from nibabel import spatialimages
from nilearn import image, plotting
from nilearn.plotting import displays

from django_dirt_ratings import datasets, models

from . import loading

N_CUTS = 5
SPATIAL_NORMALIZATION_CUTS = {
    "x": {0: -50, 1: 5, 2: 30},
    "y": {0: -65, 1: 20, 2: 54},
    "z": {0: -6, 1: 13, 2: 58},
}

_Blobs = dict[tuple[models.DisplayMode, int | None], bytes]

# The stored-image encoder settings. Pillow's AVIF plugin has no ``lossless``
# key (an unknown kwarg is silently dropped), so quality must be set explicitly:
# q90 with 4:4:4 chroma is visually lossless on QC figures (no chroma bleed on
# the one-pixel contour lines) at a fraction of true-lossless (q100) size.
# Speed 10 is libaom's fastest preset; one encoder thread because the render
# pool already saturates every core.
_AVIF_QUALITY = 90
_AVIF_SUBSAMPLING = "4:4:4"
_AVIF_SPEED = 10
_AVIF_MAX_THREADS = 1
_AVIF_KWARGS = {
    "quality": _AVIF_QUALITY,
    "subsampling": _AVIF_SUBSAMPLING,
    "speed": _AVIF_SPEED,
    "max_threads": _AVIF_MAX_THREADS,
}


# --------------------------------------------------------------------------- #
# Geometry / figure helpers (unchanged from the old _render module)
# --------------------------------------------------------------------------- #
def cuts_from_bbox_ijk(
    mask_nii: spatialimages.SpatialImage, cuts: int = 7
) -> npt.NDArray[np.float32]:
    """Find equi-spaced cuts for presenting images."""
    if mask_nii.affine is None:
        raise ValueError("nifti must have affine")
    mask_data = np.asanyarray(mask_nii.dataobj) > 0.0

    ijk_counts = [
        mask_data.sum(2).sum(1),
        mask_data.sum(2).sum(0),
        mask_data.sum(1).sum(0),
    ]

    ijk_th = np.ceil(
        [
            (mask_data.shape[1] * mask_data.shape[2]) * 0.2,  # sagittal
            (mask_data.shape[0] * mask_data.shape[2]) * 0.1,  # coronal
            (mask_data.shape[0] * mask_data.shape[1]) * 0.3,  # axial
        ]
    ).astype(int)

    vox_coords = np.zeros((4, cuts), dtype=np.float32)
    vox_coords[-1, :] = 1.0
    for ax, (c, th) in enumerate(zip(ijk_counts, ijk_th)):
        smin, smax = (0, mask_data.shape[ax] - 1)
        B = np.argwhere(c > th)
        if B.size < cuts:
            B = np.argwhere(c > 0)
        if B.size:
            smin, smax = B.min(), B.max()
        vox_coords[ax, :] = np.linspace(smin, smax, num=cuts + 2)[1:-1]

    return vox_coords


def cuts_from_bbox(
    mask_nii: spatialimages.SpatialImage, cuts: int = 7
) -> dict[models.DisplayMode, list[float]]:
    if mask_nii.affine is None:
        raise ValueError("nifti must have affine")
    vox_coords = cuts_from_bbox_ijk(mask_nii=mask_nii, cuts=cuts)
    ras_coords = mask_nii.affine.dot(vox_coords)[:3, ...]
    return {
        k: list(v)
        for k, v in zip(
            [models.DisplayMode.X, models.DisplayMode.Y, models.DisplayMode.Z],
            np.around(ras_coords, 3),
        )
    }


def _savefig(p: displays.OrthoSlicer, dst: io.BytesIO) -> None:
    """Write the slicer to ``dst`` as AVIF — the stored QC image."""
    p.savefig(
        dst,
        backend="Agg",
        format="avif",
        pil_kwargs=_AVIF_KWARGS,
    )


def rotation2canonical(img):
    """Calculate the rotation w.r.t. cardinal axes of input image."""
    img = nb.funcs.as_closest_canonical(img)
    newaff = np.diag(img.header.get_zooms()[:3])
    r = newaff @ np.linalg.pinv(img.affine[:3, :3])
    if np.allclose(r, np.eye(3)):
        return None
    return r


def rotate_affine(img, rot=None):
    """Rewrite the affine of a spatial image."""
    if rot is None:
        return img
    img = nb.funcs.as_closest_canonical(img)
    affine = np.eye(4)
    affine[:3] = rot @ img.affine[:3]
    return img.__class__(img.dataobj, affine, img.header)


@functools.lru_cache(maxsize=4)
def _template_img(path: str) -> nb.nifti1.Nifti1Image:
    """The bundled ROI template, loaded and reordered once per process."""
    img = nb.load(path)
    if not isinstance(img, nb.nifti1.Nifti1Image):  # nb.load promises FileBasedImage
        raise TypeError(f"expected a NIfTI template at {path}, got {type(img)}")
    return image.reorder_img(img, resample="continuous")


# --------------------------------------------------------------------------- #
# Per-cut drawing (one blob), used by the prep-once renderers below
# --------------------------------------------------------------------------- #
def _draw_mask(
    file_nii, mask_nii, coord: float, display_mode: models.DisplayMode, vmax: float
) -> bytes:
    f = plt.figure(figsize=(6.4, 4.8), layout="none")
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_anat(
            file_nii,
            cut_coords=[coord],
            display_mode=display_mode.name.lower(),
            figure=f,
            vmax=vmax,
            colorbar=False,
        )
        if mask_nii:
            # Outline, not filled: the filled contour costs ~4x per cut to draw.
            p.add_contours(mask_nii, levels=[0.5], colors="g")
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def _draw_surface(
    brain_nii,
    white,
    pial,
    coord: float,
    display_mode: models.DisplayMode,
    linewidths: float = 0.5,
    levels: Sequence[float] = (0.5,),
) -> bytes:
    f = plt.figure(figsize=(6.4, 4.8), layout="none")
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_anat(
            brain_nii,
            cut_coords=[coord],
            display_mode=display_mode.name.lower(),
            figure=f,
            colorbar=False,
        )
        try:
            p.add_contours(
                white, colors="b", linewidths=linewidths, levels=list(levels)
            )
            p.add_contours(pial, colors="r", linewidths=linewidths, levels=list(levels))
        except ValueError:
            pass
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def _draw_spatial_normalization(
    file_nii, template_img, coord: float, display_mode: models.DisplayMode
) -> bytes:
    f = plt.figure(figsize=(6.4, 4.8), layout="none")
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_roi(
            roi_img=template_img,
            bg_img=file_nii,
            cut_coords=[coord],
            display_mode=display_mode.name.lower(),
            figure=f,
            colorbar=False,
        )
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def _draw_fmap_frames(
    bg_nii,
    mask_nii,
    file_nii,
    file2_nii,
    coord: float,
    display_mode: models.DisplayMode,
    file_scale: tuple[float, float],
    file2_scale: tuple[float, float],
) -> bytes:
    dm = display_mode.name.lower()
    f0 = plt.figure(figsize=(6.4, 4.8), layout="none")
    f1 = plt.figure(figsize=(6.4, 4.8), layout="none")
    with io.BytesIO() as frame0, io.BytesIO() as frame1:
        p0: displays.OrthoSlicer = plotting.plot_anat(
            bg_nii,
            cut_coords=[coord],
            display_mode=dm,
            figure=f0,
            colorbar=False,
            title="func/boldref",
        )
        p0.add_overlay(file_nii, cmap="gray", vmin=file_scale[0], vmax=file_scale[1])
        try:
            p0.add_contours(mask_nii, levels=[0.5], colors="g", transparency=0.5)
        except ValueError:
            pass
        # Frames are throwaway intermediates decoded straight to arrays below, so
        # keep them as fast lossless PNG; only the stitched animation is AVIF.
        p0.savefig(
            frame0, backend="Agg", format="png", pil_kwargs={"compress_level": 1}
        )
        plt.close(f0)

        p1: displays.OrthoSlicer = plotting.plot_anat(
            bg_nii,
            cut_coords=[coord],
            display_mode=dm,
            figure=f1,
            colorbar=False,
            title="fmap/epi",
        )
        p1.add_overlay(file2_nii, cmap="gray", vmin=file2_scale[0], vmax=file2_scale[1])
        try:
            p1.add_contours(mask_nii, levels=[0.5], colors="g", transparency=0.5)
        except ValueError:
            pass
        p1.savefig(
            frame1, backend="Agg", format="png", pil_kwargs={"compress_level": 1}
        )
        plt.close(f1)

        frames = np.stack(
            [iio.imread(x, index=None) for x in [frame0.getvalue(), frame1.getvalue()]],
            axis=0,
        )
    with io.BytesIO() as buf:
        iio.imwrite(
            buf,
            frames,
            extension=".avif",
            duration=300,
            quality=_AVIF_QUALITY,
            subsampling=_AVIF_SUBSAMPLING,
            speed=_AVIF_SPEED,
            max_threads=_AVIF_MAX_THREADS,
        )
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# Prep-once renderers (one per step). Signature: (*, inputs, cuts, displays).
# --------------------------------------------------------------------------- #
def render_mask(*, inputs: dict[str, str], cuts: Sequence[int], displays_) -> _Blobs:
    mask_nii = loading.load_nifti(inputs["mask"])
    file_nii = loading.load_nifti(inputs["anat"])
    coords = cuts_from_bbox(mask_nii, cuts=N_CUTS)  # per-file
    vmax = float(np.quantile(file_nii.get_fdata(), 0.95))  # per-file
    # Reorder once per file: nilearn repeats this exact call inside every
    # plot/overlay — a full-volume resample when the affine is oblique.
    file_nii = image.reorder_img(file_nii, resample="continuous")
    mask_nii = image.reorder_img(mask_nii, resample="continuous")
    return {
        (display, cut): _draw_mask(
            file_nii, mask_nii, coords[display][cut], display, vmax
        )
        for display in displays_
        for cut in cuts
    }


def render_surface_localization(
    *, inputs: dict[str, str], cuts: Sequence[int], displays_
) -> _Blobs:
    brain_nii = loading.load_mgz(inputs["brain"])
    ribbon_nii = loading.load_mgz(inputs["ribbon"])
    coords = cuts_from_bbox(ribbon_nii, cuts=N_CUTS)  # per-file
    contour_data = ribbon_nii.get_fdata() % 39  # per-file
    white = image.new_img_like(ribbon_nii, contour_data == 2)
    pial = image.new_img_like(ribbon_nii, contour_data >= 2)
    # Derive the surfaces from the *raw* ribbon (resampling would interpolate
    # its labels), then reorder each volume once instead of per plot call.
    brain_nii = image.reorder_img(brain_nii, resample="continuous")
    white = image.reorder_img(white, resample="continuous")
    pial = image.reorder_img(pial, resample="continuous")
    return {
        (display, cut): _draw_surface(
            brain_nii, white, pial, coords[display][cut], display
        )
        for display in displays_
        for cut in cuts
    }


def render_spatial_normalization(
    *, inputs: dict[str, str], cuts: Sequence[int], displays_
) -> _Blobs:
    file_nii = image.reorder_img(
        loading.load_nifti(inputs["anat"]), resample="continuous"
    )
    template_img = _template_img(str(datasets.get_layout()))  # cached per process
    return {
        (display, cut): _draw_spatial_normalization(
            file_nii,
            template_img,
            SPATIAL_NORMALIZATION_CUTS[display.name.lower()][cut],
            display,
        )
        for display in displays_
        for cut in cuts
    }


def render_fmap_coregistration(
    *, inputs: dict[str, str], cuts: Sequence[int], displays_
) -> _Blobs:
    import nitransforms as nt

    file2_nii = loading.load_nifti(inputs["epi"])
    transform = nt.linear.load(loading._local(inputs["transform"]), reference=file2_nii)
    mask_nii = nt.resampling.apply(
        transform, spatialimage=loading._local(inputs["mask"]), order=0
    )
    boldref_nii = nb.funcs.squeeze_image(loading.load_nifti(inputs["boldref"]))
    file_nii = nt.resampling.apply(transform, spatialimage=boldref_nii)

    # Per-file prep: rotate to the EPI's canonical frame and share an empty
    # background so both animation frames have an identical, uncropped FOV.
    canonical_r = rotation2canonical(file2_nii)
    file2_nii = rotate_affine(file2_nii, rot=canonical_r)
    file_nii = rotate_affine(file_nii, rot=canonical_r)
    mask_nii = rotate_affine(mask_nii, rot=canonical_r)
    coords = cuts_from_bbox(mask_nii, cuts=N_CUTS)
    file_scale = tuple(np.quantile(file_nii.get_fdata(), [0.15, 0.998]))
    file2_scale = tuple(np.quantile(file2_nii.get_fdata(), [0.15, 0.998]))
    bg_nii = nb.Nifti1Image(
        np.zeros(file2_nii.shape), file2_nii.affine, header=file2_nii.header
    )
    # Reorder once per file (see render_mask).
    bg_nii = image.reorder_img(bg_nii, resample="continuous")
    mask_nii = image.reorder_img(mask_nii, resample="continuous")
    file_nii = image.reorder_img(file_nii, resample="continuous")
    file2_nii = image.reorder_img(file2_nii, resample="continuous")
    return {
        (display, cut): _draw_fmap_frames(
            bg_nii,
            mask_nii,
            file_nii,
            file2_nii,
            coords[display][cut],
            display,
            file_scale,
            file2_scale,
        )
        for display in displays_
        for cut in cuts
    }


def render_dtifit(*, inputs: dict[str, str], cuts, displays_) -> _Blobs:
    nii = loading.load_nifti(inputs["fa"])
    v1 = loading.load_nifti(inputs["v1"])
    v2 = loading.load_nifti(inputs["v2"])
    v3 = loading.load_nifti(inputs["v3"])

    evecs = np.stack([v1.get_fdata(), v2.get_fdata(), v3.get_fdata()], axis=-1)
    rgb = dti.color_fa(nii.get_fdata(), evecs)

    n_cuts = 20
    mask_nii = image.binarize_img(nii, 0.0001, two_sided=False, copy_header=True)
    cut_ix = cuts_from_bbox_ijk(mask_nii, cuts=n_cuts).round().astype(np.uint16)

    images: list[npt.NDArray] = []
    for cut in range(n_cuts):
        f = plt.figure(figsize=(6.4, 4.8), layout="none")
        plt.imshow(np.clip(np.rot90(rgb[:, :, cut_ix[2, cut]]), 0, 1))
        plt.axis("off")
        # Throwaway intermediates (see _draw_fmap_frames): fast PNG, in memory.
        with io.BytesIO() as img:
            plt.savefig(
                img,
                backend="Agg",
                format="png",
                pil_kwargs={"compress_level": 1},
                bbox_inches="tight",
            )
            plt.close(f)
            images.append(iio.imread(img.getvalue()))
    frames = np.stack(images + images[-2:1:-1], axis=0)

    with io.BytesIO() as buf:
        iio.imwrite(
            buf,
            frames,
            extension=".avif",
            duration=200,
            quality=_AVIF_QUALITY,
            subsampling=_AVIF_SUBSAMPLING,
            speed=_AVIF_SPEED,
            max_threads=_AVIF_MAX_THREADS,
        )
        return {(models.DisplayMode.Z, None): buf.getvalue()}


RENDERERS = {
    "mask": render_mask,
    "surface_localization": render_surface_localization,
    "spatial_normalization": render_spatial_normalization,
    "fmap_coregistration": render_fmap_coregistration,
    "dtifit": render_dtifit,
}


def render_job(*, render_key: str, inputs: dict[str, str], cuts, displays_) -> _Blobs:
    """Dispatch a RenderJob to its renderer and return all ``(display, cut)`` blobs."""
    return RENDERERS[render_key](inputs=inputs, cuts=cuts, displays_=displays_)
