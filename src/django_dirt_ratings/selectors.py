import base64
import dataclasses
import logging
import typing

from celery import result
from django import http
from django.db import models as dm

from django_dirt_ratings import models

TASK_TIMEOUT_SEC = 30


def img_type_for_step(step: int) -> str:
    """Return the image MIME subtype for a given Step value.

    This is the single source of truth used by selectors, admin, and
    anywhere else that needs to map step → image format.
    """
    match step:
        case (
            models.Step.MASK
            | models.Step.SPATIAL_NORMALIZATION
            | models.Step.SURFACE_LOCALIZATION
        ):
            return "png"
        case models.Step.FMAP_COREGISTRATION | models.Step.DTIFIT:
            return "apng"
        case _:
            return "png"


@dataclasses.dataclass
class ImageResult:
    id: int
    step: models.Step
    img: bytes

    @property
    def img_type(self) -> str:
        return img_type_for_step(self.step)

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


def _fewest_ratings_qs(
    step: models.Step,
    key: str = "source_data_issue",
    exclude_pk: int | None = None,
) -> dm.QuerySet:
    """Build a queryset that orders images by ascending rating count."""
    related = get_related_from_step(step)
    qs = models.Image.objects.filter(step=step.value)
    if exclude_pk is not None:
        qs = qs.exclude(id=exclude_pk)
    return (
        qs
        .values("id")
        .annotate(n_ratings=dm.Count(f"{related}__{key}"))
        .order_by("n_ratings")
    )


async def get_image_with_fewest_ratings(
    step: models.Step, key: str = "source_data_issue"
) -> models.Image:
    image = await _fewest_ratings_qs(step, key).afirst()
    if image is None:
        raise ValueError("No image found")

    return await models.Image.objects.aget(pk=image.get("id"))


async def get_image_pk_with_fewest_ratings(
    step: models.Step, last_pk: int, key: str = "source_data_issue"
) -> models.Image:
    image = await _fewest_ratings_qs(step, key, exclude_pk=last_pk).afirst()
    if image is None:
        raise ValueError("No image found")

    logging.info("starting to load the image from db")
    return await models.Image.objects.aget(pk=image.get("id"))
