import base64
import getpass
import io
import random
import typing
from pathlib import Path

import matplotlib
import nibabel as nb
import numpy as np
from django.db import models
from django.db.models import manager
from matplotlib import pyplot as plt
from nilearn import image, plotting
from nilearn.plotting import displays

matplotlib.use("agg")


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


class Layout(models.Model):
    src = models.CharField(max_length=256)


class Mask(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    file = models.CharField(max_length=256)
    mask = models.CharField(max_length=256)
    _mask_nii: None | nb.nifti1.Nifti1Image = None
    _file_nii: None | nb.nifti1.Nifti1Image = None

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

    def get_random_img_id(self, axis: int = 0, min_prop: float = 0.1) -> int:
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

    def get_image(
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
            p: displays.OrthoSlicer = plotting.plot_anat(
                self.file_nii,
                cut_coords=[cut_coord],
                display_mode=display_mode.name.lower(),
                figure=f,
                vmax=np.quantile(self.file_nii.get_fdata(), 0.95),
            )  # type: ignore
            try:
                p.add_contours(
                    self.mask, levels=[0.5], colors="g", filled=True, alpha=0.5
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


class MaskRating(models.Model):
    mask = models.ForeignKey(Mask, on_delete=models.CASCADE)
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField()
