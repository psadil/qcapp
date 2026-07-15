"""
Services module — write-side business logic for the django_dirt_ratings app.

Following the Django Styleguide, services take keyword-only data arguments
(never a request), validate with ``full_clean``, and are the only layer that
writes to the database.
"""

import typing

from django.contrib.gis import geos
from django.db import transaction

from django_dirt_ratings import models


def image_create(
    *,
    img: bytes,
    file1: str,
    display: int,
    step: int,
    slice: int | None = None,
    file2: str | None = None,
) -> models.Image:
    instance = models.Image(
        img=img, file1=file1, display=display, step=step, slice=slice, file2=file2
    )
    instance.full_clean()
    instance.save()
    return instance


def image_delete(*, image: models.Image) -> None:
    image.delete()


def image_upsert(
    *,
    img: bytes,
    file1: str,
    display: int,
    step: int,
    slice: int | None = None,
    file2: str | None = None,
) -> models.Image:
    """Create the Image identified by its unique metadata, or refresh its bytes.

    The lookup fields are the ``image_meta`` unique constraint; updating in
    place preserves the primary key and hence any ratings already collected.
    """
    instance = models.Image.objects.filter(
        slice=slice, file1=file1, display=display, step=step
    ).first()
    if instance is None:
        instance = models.Image(slice=slice, file1=file1, display=display, step=step)
    instance.img = img
    instance.file2 = file2
    instance.full_clean(validate_unique=False)
    instance.save()
    return instance


def session_create(*, step: int, user: str | None = None) -> models.Session:
    session = models.Session(step=step, user=user)
    session.full_clean()
    session.save()
    return session


def rating_create(
    *,
    image: models.Image,
    session: models.Session,
    rating: int,
    source_data_issue: bool = False,
    comments: str = "",
) -> models.Rating:
    instance = models.Rating(
        image=image,
        session=session,
        rating=rating,
        source_data_issue=source_data_issue,
        comments=comments,
    )
    instance.full_clean()
    instance.save()
    return instance


def annotation_bulk_create(
    *,
    image: models.Image,
    session: models.Session,
    points: typing.Sequence[tuple[float, float]],
    source_data_issue: bool = False,
    comments: str = "",
) -> list[models.Annotation]:
    """Create one Annotation per clicked point.

    An empty ``points`` still creates a single row with null geometry: it
    records a submission whose only content is the flags/comments.
    """
    common = {
        "image": image,
        "session": session,
        "source_data_issue": source_data_issue,
        "comments": comments,
    }
    if points:
        instances = [
            models.Annotation(
                **common, geometry=geos.Point(x, y, srid=models.GEOMETRY_SRID)
            )
            for x, y in points
        ]
    else:
        instances = [models.Annotation(**common)]

    for instance in instances:
        instance.full_clean(validate_constraints=False)

    with transaction.atomic():
        return models.Annotation.objects.bulk_create(instances)
