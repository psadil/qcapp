"""
Services module — write-side business logic for the django_dirt_ratings app.

Following the Django Styleguide, services take keyword-only data arguments
(never a request), validate with ``full_clean``, and are the only layer that
writes to the database.
"""

import typing

from django.db import transaction
from django.db.models import F

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
    with transaction.atomic():
        instance = models.Rating(
            image=image,
            session=session,
            rating=rating,
            source_data_issue=source_data_issue,
            comments=comments,
        )
        instance.full_clean()
        instance.save()
        # Maintain the denormalized review counter (see Image.n_reviews).
        models.Image.objects.filter(pk=image.pk).update(n_reviews=F("n_reviews") + 1)
    return instance


def annotation_create(
    *,
    image: models.Image,
    session: models.Session,
    grid_cols: int,
    grid_rows: int,
    cells: typing.Sequence[tuple[int, int, int]],
    source_data_issue: bool = False,
    comments: str = "",
) -> models.Annotation:
    """Record one annotation submission and the grid cells it marked.

    ``cells`` is a sequence of ``(col, row, rating)`` tuples. An empty
    ``cells`` still creates the Annotation (with no related cells): it records
    a submission whose only content is the flags/comments.
    """
    with transaction.atomic():
        annotation = models.Annotation(
            image=image,
            session=session,
            grid_cols=grid_cols,
            grid_rows=grid_rows,
            source_data_issue=source_data_issue,
            comments=comments,
        )
        annotation.full_clean()
        annotation.save()

        instances = [
            models.AnnotationCell(
                annotation=annotation, col=col, row=row, rating=rating
            )
            for col, row, rating in cells
        ]
        for instance in instances:
            instance.full_clean(validate_constraints=False)
        models.AnnotationCell.objects.bulk_create(instances)

        # One increment per submission (see Image.n_reviews): an annotation marked
        # with many cells still counts as a single review.
        models.Image.objects.filter(pk=image.pk).update(n_reviews=F("n_reviews") + 1)

    return annotation
