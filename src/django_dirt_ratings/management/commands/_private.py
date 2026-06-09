import io
import logging
import tempfile
import time
import typing
from datetime import datetime
from pathlib import Path
from wsgiref import handlers

import imageio.v3 as iio
import nibabel as nb
import numpy as np
import numpy.typing as npt
import polars as pl
from dipy.reconst import dti
from matplotlib import pyplot as plt
from nibabel import spatialimages
from nilearn import image, plotting
from nilearn.plotting import displays
from scipy import ndimage

from django_dirt_ratings import datasets, models

N_CUTS = 5
SPATIAL_NORMALIZATION_CUTS = {
    "x": {0: -50, 1: 5, 2: 30},
    "y": {0: -65, 1: 20, 2: 54},
    "z": {0: -6, 1: 13, 2: 58},
}


def cuts_from_bbox_ijk(
    mask_nii: spatialimages.SpatialImage, cuts: int = 7
) -> npt.NDArray[np.float32]:
    """Find equi-spaced cuts for presenting images."""
    if mask_nii.affine is None:
        raise ValueError("nifti must have affine")
    mask_data = np.asanyarray(mask_nii.dataobj) > 0.0

    # First, project the number of masked voxels on each axes
    ijk_counts = [
        mask_data.sum(2).sum(1),  # project sagittal planes to transverse (i) axis
        mask_data.sum(2).sum(0),  # project coronal planes to to longitudinal (j) axis
        mask_data.sum(1).sum(0),  # project axial planes to vertical (k) axis
    ]

    # If all voxels are masked in a slice (say that happens at k=10),
    # then the value for ijk_counts for the projection to k (ie. ijk_counts[2])
    # at that element of the orthogonal axes (ijk_counts[2][10]) is
    # the total number of voxels in that slice (ie. Ni x Nj).
    # Here we define some thresholds to consider the plane as "masked"
    # The thresholds vary because of the shape of the brain
    # I have manually found that for the axial view requiring 30%
    # of the slice elements to be masked drops almost empty boxes
    # in the mosaic of axial planes (and also addresses #281)
    ijk_th = np.ceil([
        (mask_data.shape[1] * mask_data.shape[2]) * 0.2,  # sagittal
        (mask_data.shape[0] * mask_data.shape[2]) * 0.1,  # coronal
        (mask_data.shape[0] * mask_data.shape[1]) * 0.3,  # axial
    ]).astype(int)

    vox_coords = np.zeros((4, cuts), dtype=np.float32)
    vox_coords[-1, :] = 1.0
    for ax, (c, th) in enumerate(zip(ijk_counts, ijk_th)):
        # Start with full plane if mask is seemingly empty
        smin, smax = (0, mask_data.shape[ax] - 1)

        B = np.argwhere(c > th)
        if B.size < cuts:  # Threshold too high
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
    now = datetime.now()
    stamp = time.mktime(now.timetuple())
    p.savefig(
        dst,
        metadata={"Creation Time": handlers.format_date_time(stamp)},
        backend="Agg",
        pil_kwargs={"compress_level": 9},
    )


def get_mask(
    cut: int,
    file_nii: nb.nifti1.Nifti1Image,
    mask_nii: nb.nifti1.Nifti1Image,
    display_mode: models.DisplayMode = models.DisplayMode(models.DisplayMode.X),
    figsize: tuple[float, float] = (6.4, 4.8),
) -> bytes:
    cuts = cuts_from_bbox(mask_nii, cuts=N_CUTS).get(display_mode)
    if cuts is None:
        raise ValueError("Misaglinged Display Mode")
    f = plt.figure(figsize=figsize, layout="none")
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_anat(
            file_nii,
            cut_coords=[cuts[cut]],
            display_mode=display_mode.name.lower(),
            figure=f,
            vmax=np.quantile(file_nii.get_fdata(), 0.95),
            colorbar=False,
        )
        if mask_nii:
            p.add_contours(
                mask_nii, levels=[0.5], colors="g", filled=True, transparency=0.5
            )
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def get_surface_localization(
    cut: int,
    brain_nii: nb.nifti1.Nifti1Image,
    ribbon_nii: nb.nifti1.Nifti1Image,
    display_mode: models.DisplayMode = models.DisplayMode(models.DisplayMode.X),
    figsize: tuple[float, float] = (6.4, 4.8),
    linewidths=0.5,
    levels: list[float] = [0.5],
) -> bytes:
    cuts = cuts_from_bbox(ribbon_nii, cuts=N_CUTS).get(display_mode)
    if cuts is None:
        raise ValueError("Misaglinged Display Mode")
    f = plt.figure(figsize=figsize, layout="none")
    contour_data = ribbon_nii.get_fdata() % 39
    white = image.new_img_like(ribbon_nii, contour_data == 2)
    pial = image.new_img_like(ribbon_nii, contour_data >= 2)
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_anat(
            brain_nii,
            cut_coords=[cuts[cut]],
            display_mode=display_mode.name.lower(),
            figure=f,
            colorbar=False,
        )
        try:
            p.add_contours(white, colors="b", linewidths=linewidths, levels=levels)
            p.add_contours(pial, colors="r", linewidths=linewidths, levels=levels)
        except ValueError:
            pass
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def get_spatial_normalization(
    cut: int,
    file_nii: nb.nifti1.Nifti1Image,
    display_mode: models.DisplayMode,
    figsize: tuple[float, float] = (6.4, 4.8),
) -> bytes:
    if cut > 2:
        raise ValueError("Unknown cut")

    f = plt.figure(figsize=figsize, layout="none")
    with io.BytesIO() as img:
        p: displays.OrthoSlicer = plotting.plot_roi(
            roi_img=datasets.get_layout(),
            bg_img=file_nii,
            cut_coords=[SPATIAL_NORMALIZATION_CUTS[display_mode.name.lower()][cut]],
            display_mode=display_mode.name.lower(),
            figure=f,
            colorbar=False,
        )
        _savefig(p, img)
        plt.close(f)
        return img.getvalue()


def mgz_to_nifti(src) -> nb.nifti1.Nifti1Image:
    mgh = nb.freesurfer.mghformat.load(src)
    return nb.nifti1.Nifti1Image.from_image(mgh)


def merge_or_write_image_db(d: pl.LazyFrame, dst: Path) -> None:
    if dst.exists():
        logging.info(f"Using existing database {dst}")
        joined: pl.DataFrame = (
            pl
            .scan_parquet(dst)
            .join(
                d,
                how="full",
                on=["slice", "file1", "file2", "display", "step"],
                coalesce=True,
            )
            .with_columns(match=pl.col("img") == pl.col("img_right"))
            .collect()
        )  # type: ignore
        if joined.select("match").to_series().any():
            logging.warning("Replacing images")
            logging.debug(
                joined.filter(pl.col("match")).drop(
                    pl.selectors.starts_with("img"), "match"
                )
            )
        joined.drop("img_left").write_parquet(dst)
    else:
        d.sink_parquet(dst)


async def merge_imgs(imgs: typing.Sequence[models.Image]) -> None:
    if len(imgs):
        await models.Image.objects.abulk_create(
            imgs,
            update_conflicts=True,
            update_fields=["img", "created"],
            unique_fields=["slice", "file1", "display", "step"],
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


def get_fmap_coregistration(
    cut: int,
    mask_nii: spatialimages.SpatialImage,
    file_nii: spatialimages.SpatialImage,
    file2_nii: spatialimages.SpatialImage,
    display_mode: models.DisplayMode = models.DisplayMode(models.DisplayMode.X),
    figsize: tuple[float, float] = (6.4, 4.8),
) -> bytes:
    canonical_r = rotation2canonical(file2_nii)
    file2_nii = rotate_affine(file2_nii)
    file_nii = rotate_affine(file_nii, rot=canonical_r)
    mask_nii = rotate_affine(mask_nii, rot=canonical_r)

    cuts = cuts_from_bbox(mask_nii, cuts=N_CUTS).get(display_mode)
    if cuts is None:
        raise ValueError("Misaglinged Display Mode")
    f0 = plt.figure(figsize=figsize, layout="none")
    f1 = plt.figure(figsize=figsize, layout="none")

    with io.BytesIO() as frame0:
        with io.BytesIO() as frame1:
            # Create an empty background image to enforce identical, uncropped FOV for both frames
            bg_nii = nb.Nifti1Image(
                np.zeros(file2_nii.shape), file2_nii.affine, header=file2_nii.header
            )

            # https://github.com/nipreps/nireports/blob/e7beccc14670e820c646306eb1d7dd3d56591450/nireports/reportlets/utils.py#L62-L70
            p0: displays.OrthoSlicer = plotting.plot_anat(
                bg_nii,
                cut_coords=[cuts[cut]],
                display_mode=display_mode.name.lower(),
                figure=f0,
                colorbar=False,
                title="func/boldref",
            )
            p0.add_overlay(
                file_nii,
                cmap="gray",
                vmax=np.quantile(file_nii.get_fdata(), 0.998),
                vmin=np.quantile(file_nii.get_fdata(), 0.15),
            )
            try:
                p0.add_contours(mask_nii, levels=[0.5], colors="g", transparency=0.5)
            except ValueError:
                pass
            _savefig(p0, frame0)
            plt.close(f0)

            # https://github.com/nipreps/nireports/blob/e7beccc14670e820c646306eb1d7dd3d56591450/nireports/reportlets/utils.py#L62-L70
            p1: displays.OrthoSlicer = plotting.plot_anat(
                bg_nii,
                cut_coords=[cuts[cut]],
                display_mode=display_mode.name.lower(),
                figure=f1,
                colorbar=False,
                title="fmap/epi",
            )
            p1.add_overlay(
                file2_nii,
                cmap="gray",
                vmax=np.quantile(file2_nii.get_fdata(), 0.998),
                vmin=np.quantile(file2_nii.get_fdata(), 0.15),
            )
            try:
                p1.add_contours(mask_nii, levels=[0.5], colors="g", transparency=0.5)
            except ValueError:
                pass
            _savefig(p1, frame1)
            plt.close(f1)

            frames = np.stack(
                [
                    iio.imread(x, index=None)
                    for x in [frame0.getvalue(), frame1.getvalue()]
                ],
                axis=0,
            )
        with io.BytesIO() as buf:
            iio.imwrite(buf, frames, extension=".apng", loop=0, duration=300)
            return buf.getvalue()


def get_dtifit(
    nii: nb.nifti1.Nifti1Image,
    v1: nb.nifti1.Nifti1Image,
    v2: nb.nifti1.Nifti1Image,
    v3: nb.nifti1.Nifti1Image,
    figsize: tuple[float, float] = (6.4, 4.8),
) -> bytes:
    evecs = np.stack([v1.get_fdata(), v2.get_fdata(), v3.get_fdata()], axis=-1)
    rgb = dti.color_fa(nii.get_fdata(), evecs)

    n_cuts = 20
    mask_nii: nb.nifti1.Nifti1Image = image.binarize_img(
        nii, 0.0001, two_sided=False, copy_header=True
    )
    cuts = cuts_from_bbox_ijk(mask_nii, cuts=n_cuts).round().astype(np.uint16)

    with tempfile.TemporaryDirectory() as _tmpd:
        tmpd = Path(_tmpd)
        images: list[Path] = []
        for cut in range(n_cuts):
            plt.figure(figsize=figsize, layout="none")
            plt.imshow(np.clip(ndimage.rotate(rgb[:, :, cuts[2, cut]], 90), 0, 1))
            img = tmpd / f"{cut}.png"
            plt.axis("off")
            plt.savefig(
                img,
                backend="Agg",
                pil_kwargs={"compress_level": 9},
                bbox_inches="tight",
            )
            plt.close()
            images.append(img)

        frames = np.stack([iio.imread(img) for img in images + images[-2:1:-1]], axis=0)

    with io.BytesIO() as buf:
        iio.imwrite(buf, frames, extension=".apng", loop=0, duration=200)
        return buf.getvalue()
