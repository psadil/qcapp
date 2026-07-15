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


def image_file_exists(*, file1: str, step: int) -> bool:
    """Whether any Image for this source file + step exists.

    Used by ingest to skip re-rendering a whole file's series when not updating.
    """
    return models.Image.objects.filter(file1=file1, step=step).exists()


def image_list(
    *, step: models.Step | None = None, limit: int = 100
) -> dm.QuerySet[models.Image]:
    qs = models.Image.objects.all()
    if step is not None:
        qs = qs.filter(step=step)
    return qs[:limit]


def rating_list() -> dm.QuerySet[models.Rating]:
    return models.Rating.objects.select_related("session", "image").all()


def image_with_fewest_ratings(
    *, step: models.Step, exclude: int | None = None
) -> models.Image:
    """The next image to rate for a step: the one with fewest submissions.

    Ordered by the denormalized ``Image.n_reviews`` counter (maintained by the
    services layer, one increment per Rating/Annotation submission) and then by
    ``id``. Backed by the ``image_next`` index, this is an index range seek that
    reads a single leaf entry — no aggregate scan over the whole step.
    """
    qs = models.Image.objects.filter(step=step.value)
    if exclude is not None:
        qs = qs.exclude(id=exclude)
    image_id = qs.order_by("n_reviews", "id").values_list("id", flat=True).first()
    if image_id is None:
        raise exceptions.ApplicationError("No image found")

    return models.Image.objects.get(pk=image_id)
