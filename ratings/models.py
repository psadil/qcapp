import abc
import base64
import getpass
import io
import json
import random
import typing
from pathlib import Path

import matplotlib
import nibabel as nb
import numpy as np
from django import http, shortcuts
from django.db import models
from django.db.models import manager
from matplotlib import pyplot as plt
from nilearn import image, plotting
from nilearn.plotting import displays

matplotlib.use("agg")


class Step(models.IntegerChoices):
    MASK = 0
    SPATIAL_NORMALIZATION = 1
    SURFACE_LOCALIZATION = 2
    FMAP_COREGISTRATION = 3


class Ratings(models.IntegerChoices):
    PASS = 0
    UNSURE = 1
    FAIL = 2
    NOT_INFORMATIVE = 3


class DisplayMode(models.IntegerChoices):
    X = 0
    Y = 1
    Z = 2

    @classmethod
    def get_random(cls) -> int:
        return random.choice(cls.values)


class SpatialNormalizationView(models.IntegerChoices):
    X0 = 0
    X1 = 1
    X2 = 2
    Y0 = 3
    Y1 = 4
    Y2 = 5
    Z0 = 6
    Z1 = 7
    Z2 = 8

    @classmethod
    def get_random(cls) -> int:
        return random.choice(cls.values)


class Layout(models.Model):
    src = models.CharField(max_length=256)
    step = models.IntegerField(choices=Step.choices)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pk=}, {self.src=}, {self.step=}"


class Mask(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    file = models.CharField(max_length=256, unique=True)
    mask = models.CharField(max_length=256, unique=True)
    _mask_nii: None | nb.nifti1.Nifti1Image = None
    _file_nii: None | nb.nifti1.Nifti1Image = None
    _n_cuts: int = 7

    def __str__(self):
        mask = Path(self.mask)
        file = Path(self.file)
        return f"Mask {self.pk}: {mask.name}, {file.name}"

    @property
    def mask_nii(self) -> nb.nifti1.Nifti1Image:
        if self._mask_nii is None:
            self._mask_nii = nb.nifti1.Nifti1Image.load(self.mask)
        return self._mask_nii

    @property
    def file_nii(self) -> nb.nifti1.Nifti1Image:
        if self._file_nii is None:
            self._file_nii = nb.nifti1.Nifti1Image.load(self.file)
        return self._file_nii

    @classmethod
    def get_masks_from_layout(cls, layout: Layout) -> manager.BaseManager[typing.Self]:
        return cls.objects.filter(layout_id=layout)

    def get_random_img_id(self) -> int:
        return random.choice(range(self._n_cuts))

    def get_random_mask_from_layout(self, layout: Layout) -> typing.Self:
        return random.choice(self.get_masks_from_layout(layout=layout))

    async def get_image(
        self,
        img_id: int,
        display_mode: DisplayMode = DisplayMode(DisplayMode.X),
        figsize: tuple[float, float] = (6.4, 4.8),
    ) -> str:
        cuts = cuts_from_bbox(self.mask_nii, cuts=self._n_cuts).get(display_mode)
        if cuts is None:
            raise ValueError("Misaglinged Display Mode")
        f = plt.figure(figsize=figsize, layout="none")
        with io.BytesIO() as img:
            p: displays.OrthoSlicer = plotting.plot_anat(
                self.file_nii,
                cut_coords=[cuts[img_id]],
                display_mode=display_mode.name.lower(),
                figure=f,
                vmax=np.quantile(self.file_nii.get_fdata(), 0.95),
            )  # type: ignore
            try:
                p.add_contours(
                    self.mask_nii, levels=[0.5], colors="g", filled=True, alpha=0.5
                )
            except ValueError:
                pass
            p.savefig(img)
            return base64.b64encode(img.getvalue()).decode()


class Rating(models.Model):
    rating = models.IntegerField(choices=Ratings.choices, default=None, verbose_name="")
    source_data_issue = models.BooleanField(
        default=False, verbose_name="Source Data Issue"
    )
    user = models.CharField(max_length=16, default=getpass.getuser)
    created = models.DateTimeField(auto_now_add=True)


class BaseRating:
    @classmethod
    @abc.abstractmethod
    async def from_request_rating(
        cls, request: http.HttpRequest, rating: Rating
    ) -> typing.Self:
        raise NotImplementedError


class MaskRating(BaseRating, models.Model):
    mask = models.ForeignKey(Mask, on_delete=models.CASCADE)
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField()
    display_id = models.IntegerField(choices=DisplayMode.choices)

    @classmethod
    async def from_request_rating(
        cls, request: http.HttpRequest, rating: Rating
    ) -> typing.Self:
        extra = get_extra_from_request(request)
        mask = shortcuts.aget_object_or_404(  # type: ignore
            Mask, pk=extra.get("mask_id")
        )
        return await cls.objects.acreate(
            rating=rating,
            img_id=extra.get("img_id"),
            mask=await mask,
            display_id=extra.get("display_id"),
        )


class SpatialNormalization(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    file = models.CharField(max_length=256)
    _file_nii: None | nb.nifti1.Nifti1Image = None

    @property
    def file_nii(self) -> nb.nifti1.Nifti1Image:
        if self._file_nii is None:
            self._file_nii = nb.nifti1.Nifti1Image.load(self.file)
        assert isinstance(self._file_nii, nb.nifti1.Nifti1Image)
        return self._file_nii

    async def get_image(
        self,
        view: SpatialNormalizationView = SpatialNormalizationView(
            SpatialNormalizationView.X0
        ),
        figsize: tuple[float, float] = (6.4, 4.8),
    ) -> str:
        match view:
            case SpatialNormalizationView.X0:
                cut_coord = -50
                display_mode = "x"
            case SpatialNormalizationView.X1:
                cut_coord = -8
                display_mode = "x"
            case SpatialNormalizationView.X2:
                cut_coord = 30
                display_mode = "x"
            case SpatialNormalizationView.Y0:
                cut_coord = -65
                display_mode = "y"
            case SpatialNormalizationView.Y1:
                cut_coord = -20
                display_mode = "y"
            case SpatialNormalizationView.Y2:
                cut_coord = 54
                display_mode = "y"
            case SpatialNormalizationView.Z0:
                cut_coord = -6
                display_mode = "z"
            case SpatialNormalizationView.Z1:
                cut_coord = 13
                display_mode = "z"
            case SpatialNormalizationView.Z2:
                cut_coord = 58
                display_mode = "z"
            case _:
                raise ValueError("Unknown view")

        f = plt.figure(figsize=figsize, layout="none")
        with io.BytesIO() as img:
            p: displays.OrthoSlicer = plotting.plot_roi(
                roi_img="ratings/static/ratings/mask_all_layout_smoothed2.nii.gz",
                bg_img=self.file_nii,
                cut_coords=[cut_coord],
                display_mode=display_mode,
                figure=f,
            )  # type: ignore
            p.savefig(img)
            return base64.b64encode(img.getvalue()).decode()


class SpatialNormalizationRating(BaseRating, models.Model):
    spatial_normalization = models.ForeignKey(
        SpatialNormalization, on_delete=models.CASCADE
    )
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField(choices=SpatialNormalizationView.choices)

    @classmethod
    async def from_request_rating(
        cls, request: http.HttpRequest, rating: Rating
    ) -> typing.Self:
        extra = get_extra_from_request(request)
        spatial_normalization = shortcuts.aget_object_or_404(  # type: ignore
            SpatialNormalization, pk=extra.get("spatial_normalization_id")
        )
        return await cls.objects.acreate(
            rating=rating,
            img_id=extra.get("img_id"),
            spatial_normalization=await spatial_normalization,
        )


class SurfaceLocalization(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    anat = models.CharField(max_length=256, unique=True)
    ribbon = models.CharField(max_length=256, unique=True)
    _anat_nii: None | nb.nifti1.Nifti1Image = None
    _ribbon_nii: None | nb.nifti1.Nifti1Image = None
    _n_cuts: int = 7

    @property
    def ribbon_nii(self) -> nb.nifti1.Nifti1Image:
        if self._ribbon_nii is None:
            self._ribbon_nii = mgz_to_nifti(self.ribbon)
        return self._ribbon_nii

    @property
    def anat_nii(self) -> nb.nifti1.Nifti1Image:
        if self._anat_nii is None:
            self._anat_nii = mgz_to_nifti(self.anat)
        return self._anat_nii

    @classmethod
    def get_masks_from_layout(cls, layout: Layout) -> manager.BaseManager[typing.Self]:
        return cls.objects.filter(layout_id=layout)

    def get_random_img_id(self) -> int:
        return random.choice(range(self._n_cuts))

    def get_random_mask_from_layout(self, layout: Layout) -> typing.Self:
        return random.choice(self.get_masks_from_layout(layout=layout))

    async def get_image(
        self,
        img_id: int,
        display_mode: DisplayMode = DisplayMode(DisplayMode.X),
        figsize: tuple[float, float] = (6.4, 4.8),
        levels: list[float] = [0.5],
        linewidths: float = 0.5,
    ) -> str:
        cuts = cuts_from_bbox(self.ribbon_nii, cuts=self._n_cuts).get(display_mode)
        if cuts is None:
            raise ValueError("Misaglinged Display Mode")
        f = plt.figure(figsize=figsize, layout="none")
        contour_data = self.ribbon_nii.get_fdata() % 39
        white = image.new_img_like(self.ribbon_nii, contour_data == 2)
        pial = image.new_img_like(self.ribbon_nii, contour_data >= 2)
        with io.BytesIO() as img:
            p: displays.OrthoSlicer = plotting.plot_anat(
                self.anat_nii,
                cut_coords=[cuts[img_id]],
                display_mode=display_mode.name.lower(),
                figure=f,
            )  # type: ignore
            try:
                p.add_contours(white, colors="b", linewidths=linewidths, levels=levels)
                p.add_contours(pial, colors="r", linewidths=linewidths, levels=levels)
            except ValueError:
                pass
            p.savefig(img)
            return base64.b64encode(img.getvalue()).decode()


class SurfaceLocalizationRating(BaseRating, models.Model):
    surface_localization = models.ForeignKey(
        SurfaceLocalization, on_delete=models.CASCADE
    )
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField()
    display_id = models.IntegerField(choices=DisplayMode.choices)

    @classmethod
    async def from_request_rating(
        cls, request: http.HttpRequest, rating: Rating
    ) -> typing.Self:
        extra = get_extra_from_request(request)
        surface_localization = shortcuts.aget_object_or_404(  # type: ignore
            SurfaceLocalization, pk=extra.get("surface_localization_id")
        )
        return await cls.objects.acreate(
            rating=rating,
            img_id=extra.get("img_id"),
            surface_localization=await surface_localization,
            display_id=extra.get("display_id"),
        )


class FMapCoregistration(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    file = models.CharField(max_length=256, unique=True)
    mask = models.CharField(max_length=256, unique=True)
    _mask_nii: None | nb.nifti1.Nifti1Image = None
    _file_nii: None | nb.nifti1.Nifti1Image = None

    @property
    def mask_nii(self) -> nb.nifti1.Nifti1Image:
        if self._mask_nii is None:
            self._mask_nii = nb.nifti1.Nifti1Image.load(self.mask)
        return self._mask_nii

    @property
    def file_nii(self) -> nb.nifti1.Nifti1Image:
        if self._file_nii is None:
            self._file_nii = nb.nifti1.Nifti1Image.load(self.file)
        return self._file_nii

    @classmethod
    def get_masks_from_layout(cls, layout: Layout) -> manager.BaseManager[typing.Self]:
        return cls.objects.filter(layout_id=layout)

    def get_random_img_id(self, axis: int = 0, min_prop: float = 0.2) -> int:
        data = np.asarray(self.mask_nii.get_fdata(), dtype=np.bool)
        while True:
            slice = random.choice(range(self.mask_nii.shape[axis]))
            if axis == 0:
                out = data[slice, :, :]
            elif axis == 1:
                out = data[:, slice, :]
            else:
                out = data[:, :, slice]
            if np.mean(out) > min_prop:
                break
        return slice

    def get_random_mask_from_layout(self, layout: Layout) -> typing.Self:
        return random.choice(self.get_masks_from_layout(layout=layout))

    async def get_image(
        self,
        img_id: int,
        display_mode: DisplayMode = DisplayMode(DisplayMode.X),
        figsize: tuple[float, float] = (6.4, 4.8),
    ) -> str:
        cut_coord = image.coord_transform(img_id, img_id, img_id, self.mask_nii.affine)[
            display_mode.value
        ]
        f = plt.figure(figsize=figsize, layout="none")
        with io.BytesIO() as img:
            # https://github.com/nipreps/nireports/blob/e7beccc14670e820c646306eb1d7dd3d56591450/nireports/reportlets/utils.py#L62-L70
            p: displays.OrthoSlicer = plotting.plot_anat(
                self.file_nii,
                cut_coords=[cut_coord],
                display_mode=display_mode.name.lower(),
                figure=f,
                vmax=np.quantile(self.file_nii.get_fdata(), 0.998),
                vmin=np.quantile(self.file_nii.get_fdata(), 0.15),
            )  # type: ignore
            try:
                p.add_contours(self.mask_nii, levels=[0.5], colors="g", alpha=0.5)
            except ValueError:
                pass
            p.savefig(img)
            return base64.b64encode(img.getvalue()).decode()


class FMapCoregistrationRating(BaseRating, models.Model):
    fmap_coregistration = models.ForeignKey(
        FMapCoregistration, on_delete=models.CASCADE
    )
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField()
    display_id = models.IntegerField(choices=DisplayMode.choices)

    @classmethod
    async def from_request_rating(
        cls, request: http.HttpRequest, rating: Rating
    ) -> typing.Self:
        extra = get_extra_from_request(request)
        fmap_coregistration = shortcuts.aget_object_or_404(  # type: ignore
            FMapCoregistration, pk=extra.get("fmap_coregistration_id")
        )
        return await cls.objects.acreate(
            rating=rating,
            img_id=extra.get("img_id"),
            fmap_coregistration=await fmap_coregistration,
            display_id=extra.get("display_id"),
        )


def get_extra_from_request(request: http.HttpRequest) -> dict[str, typing.Any]:
    extra_list: str | None = request.POST.get("extra")
    if extra_list is None:
        raise http.Http404("Missing extra")
    return json.loads(extra_list)


def mgz_to_nifti(src) -> nb.nifti1.Nifti1Image:
    mgh = nb.freesurfer.mghformat.load(src)
    return nb.nifti1.Nifti1Image.from_image(mgh)


def cuts_from_bbox(
    mask_nii: nb.nifti1.Nifti1Image, cuts: int = 7
) -> dict[DisplayMode, list[float]]:
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
        # Start with full plane if mask is seemingly empty
        smin, smax = (0, mask_data.shape[ax] - 1)

        B = np.argwhere(c > th)
        if B.size < cuts:  # Threshold too high
            B = np.argwhere(c > 0)
        if B.size:
            smin, smax = B.min(), B.max()

        vox_coords[ax, :] = np.linspace(smin, smax, num=cuts + 2)[1:-1]

    ras_coords = mask_nii.affine.dot(vox_coords)[:3, ...]
    return {
        k: list(v)
        for k, v in zip(
            [DisplayMode.X, DisplayMode.Y, DisplayMode.Z], np.around(ras_coords, 3)
        )
    }
