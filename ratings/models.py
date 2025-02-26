import base64
import getpass
import io
import random
import typing
from pathlib import Path

import nibabel as nb
from django.db import models
from django.db.models import manager
from matplotlib import figure
from nilearn import image, plotting
from nilearn.plotting import displays


class Ratings(models.IntegerChoices):
    PASS = 0
    UNSURE = 1
    FAIL = 2
    NEEDS_REVIEW = 3
    NOT_INFORMATIVE = 4


class DisplayMode(models.IntegerChoices):
    X = 0
    Y = 1
    Z = 2

    @classmethod
    def get_random(cls) -> int:
        return random.choice(cls.values)


class Step(models.TextChoices):
    IMAGE = "I"
    MASK = "M"


class Layout(models.Model):
    src = models.CharField(max_length=256)


class Mask(models.Model):
    layout = models.ForeignKey(Layout, on_delete=models.CASCADE)
    file = models.CharField(max_length=256)
    mask = models.CharField(max_length=256)

    def __str__(self):
        mask = Path(self.mask)
        file = Path(self.file)
        return f"Mask {self.pk}: {mask.name}, {file.name}"

    @classmethod
    def get_masks_from_layout(cls, layout: Layout) -> manager.BaseManager[typing.Self]:
        return cls.objects.filter(layout_id=layout)

    def get_random_img_id(self, axis: int = 0) -> int:
        mask = nb.nifti1.Nifti1Image.load(self.mask)
        return random.choice(range(mask.shape[axis]))

    def get_random_mask_from_layout(self, layout: Layout) -> typing.Self:
        return random.choice(self.get_masks_from_layout(layout=layout))

    def get_image(
        self,
        img_id: int,
        display_mode: DisplayMode = DisplayMode(DisplayMode.X),
        figsize: tuple[float, float] = (6.4, 4.8),
    ) -> str:
        nii = nb.nifti1.Nifti1Image.load(self.mask)
        cut_coord = image.coord_transform(img_id, img_id, img_id, nii.affine)[
            display_mode.value
        ]
        f = figure.Figure(figsize=figsize, layout=None)
        with io.BytesIO() as img:
            p: displays.OrthoSlicer = plotting.plot_anat(
                self.file,
                cut_coords=[cut_coord],
                display_mode=display_mode.name.lower(),
                figure=f,
            )  # type: ignore
            try:
                p.add_contours(
                    self.mask, levels=[0.5], colors="g", filled=True, alpha=0.5
                )
            except ValueError:
                pass
            p.savefig(img)
            return base64.b64encode(img.getvalue()).decode()


def get_default_user() -> str:
    return getpass.getuser()


class Rating(models.Model):
    rating = models.IntegerField(
        choices=Ratings.choices, default=Ratings.NOT_INFORMATIVE
    )
    user = models.CharField(max_length=16, default=get_default_user)
    created = models.DateTimeField(auto_now_add=True)


class MaskRating(models.Model):
    mask = models.ForeignKey(Mask, on_delete=models.CASCADE)
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE)
    img_id = models.IntegerField()
