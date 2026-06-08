import json
import random
import typing

from django import http, shortcuts
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

    def add_request_args(self, request: http.HttpRequest) -> None:
        self.image = shortcuts.get_object_or_404(
            Image, pk=request.session.get("image_id")
        )
        self.session = shortcuts.get_object_or_404(
            Session, pk=request.session.get("session_id")
        )

    def update_instance_and_save(self, request: http.HttpRequest) -> None:
        self.add_request_args(request)
        self.save()


class ClickedCoordinate(FromRequest):
    x = models.FloatField(null=True)
    y = models.FloatField(null=True)

    def update_instance_and_save(self, request: http.HttpRequest) -> None:
        self.add_request_args(request)
        points_raw = request.POST.get("points")

        points = [] if points_raw is None else json.loads(points_raw)

        if len(points) == 0:
            self.save()
        else:
            common_fields = {}
            for field in self._meta.get_fields():
                if (
                    field.concrete
                    and not field.auto_created
                    and field.name != "id"
                    and field.name != "pk"
                ):
                    common_fields.update({field.name: getattr(self, field.name)})
            objs = []
            for point in points:
                objs.append(self.__class__(**{**common_fields, **point}))
            self.__class__.objects.bulk_create(objs)


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, default=None, verbose_name="")
