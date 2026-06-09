import random
import typing

from django.db import models


class Step(models.IntegerChoices):
    MASK = 0
    SPATIAL_NORMALIZATION = 1
    SURFACE_LOCALIZATION = 2
    FMAP_COREGISTRATION = 3
    DTIFIT = 4


class Ratings(models.IntegerChoices):
    PASS = 0
    UNSURE = 1
    FAIL = 2


class DisplayMode(models.IntegerChoices):
    X = 0
    Y = 1
    Z = 2

    @classmethod
    def get_random(cls) -> int:
        return random.choice(cls.values)


class Session(models.Model):
    step = models.IntegerField(choices=Step.choices)
    created = models.DateTimeField(auto_now_add=True)
    user = models.TextField(default=None, null=True)


class Image(models.Model):
    img = models.BinaryField()
    slice = models.IntegerField(null=True)
    file1 = models.TextField(max_length=512)
    file2 = models.TextField(max_length=512, null=True)
    display = models.IntegerField(choices=DisplayMode.choices)
    step = models.IntegerField(choices=Step.choices)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slice", "file1", "display", "step"], name="image_meta"
            )
        ]

    def to_dict(self) -> dict[str, typing.Any]:
        return {"id": self.pk, "step": self.step, "img": self.img}


class FromRequest(models.Model):
    """Abstract base for models submitted during a rating session."""

    class Meta:
        abstract = True

    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    source_data_issue = models.BooleanField(
        default=False,
        verbose_name="I suspect there might be a problem with the image quality",
    )
    comments = models.TextField(
        default="",
        help_text="Please only add additional comments if necessary.",
        blank=True,
    )
    created = models.DateTimeField(auto_now_add=True)


class ClickedCoordinate(FromRequest):
    x = models.FloatField(null=True)
    y = models.FloatField(null=True)


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, default=None, verbose_name="")
