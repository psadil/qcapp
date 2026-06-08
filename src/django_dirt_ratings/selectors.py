import base64
import dataclasses
import logging
import typing

from celery import result
from django import http
from django.db import models as dm

from django_dirt_ratings import models

TASK_TIMEOUT_SEC = 30


@dataclasses.dataclass
class ImageResult:
    id: int
    step: models.Step
    img: bytes

    @property
    def img_type(self) -> str:
        match self.step:
            case (
                models.Step.MASK
                | models.Step.SPATIAL_NORMALIZATION
                | models.Step.SURFACE_LOCALIZATION
            ):
                related = "png"
            case models.Step.FMAP_COREGISTRATION | models.Step.DTIFIT:
                related = "apng"
            case _:
                raise AssertionError("Unknown step")
        return related

    @property
    def img_decoded(self) -> str:
        return base64.b64encode(self.img).decode()


def get_related_from_step(step: models.Step) -> str:
    match step:
        case (
            models.Step.MASK
            | models.Step.SPATIAL_NORMALIZATION
            | models.Step.SURFACE_LOCALIZATION
        ):
            related = "clickedcoordinate"
        case _:
            related = "rating"
    return related


async def get_img_id(request: http.HttpRequest) -> ImageResult:
    logging.info("looking for img task")
    img_task = await request.session.aget("img_task")
    if img_task is None:
        raise http.Http404("no img_task found")
    res = result.AsyncResult(img_task)

    logging.info(f"getting results of {res=}")
    img: dict[str, typing.Any] = res.get(timeout=TASK_TIMEOUT_SEC)

    return ImageResult(**img)


async def get_image_with_fewest_ratings(
    step: models.Step, key: str = "source_data_issue"
) -> models.Image:
    related = get_related_from_step(step)
    image = await (
        models.Image.objects.filter(step=step.value)
        .select_related(related)
        .values("id")
        .annotate(n_ratings=dm.Count(f"{related}__{key}"))
        .order_by("n_ratings")
        .afirst()
    )
    if image is None:
        raise ValueError("No image found")

    return await models.Image.objects.aget(pk=image.get("id"))


async def get_image_pk_with_fewest_ratings(
    step: models.Step, last_pk: int, key: str = "source_data_issue"
) -> models.Image:
    related = get_related_from_step(step)
    image = await (
        models.Image.objects.filter(step=step.value)
        .exclude(id__in=[last_pk])
        .select_related(related)
        .values("id")
        .annotate(n_ratings=dm.Count(f"{related}__{key}"))
        .order_by("n_ratings")
        .afirst()
    )
    if image is None:
        raise ValueError("No image found")

    logging.info("starting to load the image from db")
    return await models.Image.objects.aget(pk=image.get("id"))
