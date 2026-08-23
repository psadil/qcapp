"""
Selectors module — read-side data access for the django_dirt_ratings app.

Following the Django Styleguide, selectors take keyword-only arguments and
raise domain errors; HTTP concerns stay in views and APIs.
"""

from django.db import models as dm

from django_dirt_ratings import exceptions, models, ordering


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


def image_files_rendered(*, step: int) -> set[str]:
    """The ``file1`` values that already have Images for this step.

    Used by ingest to skip re-rendering whole files when not updating: one
    set-returning query, where a per-file existence probe would walk the step's
    rows (no index leads with ``file1``) once per discovered job.
    """
    return set(
        models.Image.objects.filter(step=step)
        .values_list("file1", flat=True)
        .distinct()
    )


def image_list(
    *, step: models.Step | None = None, limit: int = 100
) -> dm.QuerySet[models.Image]:
    qs = models.Image.objects.all()
    if step is not None:
        qs = qs.filter(step=step)
    return qs[:limit]


def rating_list() -> dm.QuerySet[models.Rating]:
    return models.Rating.objects.select_related("session", "image").all()


def next_image(
    *,
    step: models.Step,
    strategy: ordering.OrderingStrategy,
    exclude: int | None = None,
) -> models.Image:
    """The next image to serve for a step under a review-ordering ``strategy``.

    The strategy owns the filter/order (see :mod:`~django_dirt_ratings.ordering`);
    every strategy is a single index seek. ``exclude`` drops the image just shown so
    a tie doesn't re-serve it. Raises :class:`exceptions.ApplicationError` when the
    step has no image to serve (e.g. a triage pool that has been exhausted).
    """
    qs = models.Image.objects.filter(step=step.value)
    if exclude is not None:
        qs = qs.exclude(id=exclude)
    image_id = strategy.order(qs).values_list("id", flat=True).first()
    if image_id is None:
        raise exceptions.ApplicationError("No image found")

    return models.Image.objects.get(pk=image_id)


def image_with_fewest_ratings(
    *, step: models.Step, exclude: int | None = None
) -> models.Image:
    """The next image to rate for a step under the breadth-first strategy.

    Thin delegate over :func:`next_image` — the least-reviewed image, backed by the
    ``image_next`` index. Retained for callers/tests that want breadth-first directly.
    """
    return next_image(step=step, strategy=ordering.BreadthFirst(), exclude=exclude)
