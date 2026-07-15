"""
Selectors module — read-side data access for the django_dirt_ratings app.

Following the Django Styleguide, selectors take keyword-only arguments and
raise domain errors; HTTP concerns stay in views and APIs.
"""

from django.db import models as dm

from django_dirt_ratings import exceptions, models


def image_get(*, image_id: int) -> models.Image:
    """Fetch a single Image; raises :class:`exceptions.NotFound`."""
    try:
        return models.Image.objects.get(pk=image_id)
    except models.Image.DoesNotExist as e:
        raise exceptions.NotFound(f"Image {image_id} not found") from e


def session_get(*, session_id: int) -> models.Session:
    """Fetch a single Session; raises :class:`exceptions.NotFound`."""
    try:
        return models.Session.objects.get(pk=session_id)
    except models.Session.DoesNotExist as e:
        raise exceptions.NotFound(f"Session {session_id} not found") from e


def image_exists(
    *, file1: str, display: int, step: int, slice: int | None = None
) -> bool:
    """Whether an Image with this ``image_meta`` identity already exists."""
    return models.Image.objects.filter(
        slice=slice, file1=file1, display=display, step=step
    ).exists()


def image_list(
    *, step: models.Step | None = None, limit: int = 100
) -> dm.QuerySet[models.Image]:
    qs = models.Image.objects.all()
    if step is not None:
        qs = qs.filter(step=step)
    return qs[:limit]


def rating_list() -> dm.QuerySet[models.Rating]:
    return models.Rating.objects.select_related("session", "image").all()


def _fewest_ratings_qs(
    *,
    step: models.Step,
    exclude_pk: int | None = None,
) -> dm.QuerySet:
    """Order a step's images by ascending number of review submissions.

    Counts distinct submission rows (Rating/Annotation), so an image reviewed
    once but marked with many cells does not look "more reviewed" than one
    reviewed several times.
    """
    qs = models.Image.objects.filter(step=step.value)
    if exclude_pk is not None:
        qs = qs.exclude(id=exclude_pk)
    return (
        qs.values("id")
        .annotate(n_ratings=dm.Count(step.related_name, distinct=True))
        .order_by("n_ratings")
    )


def image_with_fewest_ratings(
    *, step: models.Step, exclude: int | None = None
) -> models.Image:
    """The next image to rate for a step: the one with fewest submissions."""
    image = _fewest_ratings_qs(step=step, exclude_pk=exclude).first()
    if image is None:
        raise exceptions.ApplicationError("No image found")

    return models.Image.objects.get(pk=image.get("id"))
