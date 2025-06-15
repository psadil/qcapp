import json
import random

from asgiref import sync
from django import forms, http, shortcuts
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


class FromRequest(models.Model):
    class Meta:
        abstract = True

    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    source_data_issue = models.BooleanField(
        default=False, verbose_name="Source Data Issue"
    )
    created = models.DateTimeField(auto_now_add=True)

    @classmethod
    async def from_request_form(
        cls, request: http.HttpRequest, form: forms.ModelForm
    ) -> None:
        image = shortcuts.aget_object_or_404(  # type: ignore
            Image,
            pk=await request.session.aget("image_id"),  # type: ignore
        )
        session = shortcuts.aget_object_or_404(  # type: ignore
            Session,
            pk=await request.session.aget("session_id"),  # type: ignore
        )

        await cls.objects.acreate(
            image=await image, **form.cleaned_data, session=await session
        )


class ClickedCoordinate(FromRequest):
    x = models.FloatField(null=True)
    y = models.FloatField(null=True)

    @classmethod
    async def from_request_form(
        cls, request: http.HttpRequest, form: forms.ModelForm
    ) -> None:
        image = await shortcuts.aget_object_or_404(  # type: ignore
            Image,
            pk=await request.session.aget("image_id"),  # type: ignore
        )
        session = await shortcuts.aget_object_or_404(  # type: ignore
            Session,
            pk=await request.session.aget("session_id"),  # type: ignore
        )
        points_raw = request.POST.get("points")

        points = [] if points_raw is None else json.loads(points_raw)

        if len(points) == 0:
            await cls.objects.acreate(
                image=image,
                **form.cleaned_data,
                session=session,
            )
        else:
            objs = []

            for point in points:
                objs.append(
                    cls(
                        image=image,
                        session=session,
                        x=point["x"],
                        y=point["y"],
                        **form.cleaned_data,
                    )
                )
            await sync.sync_to_async(cls.objects.bulk_create)(objs)


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, default=None, verbose_name="")


class DynamicRating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, default=None, verbose_name="")
