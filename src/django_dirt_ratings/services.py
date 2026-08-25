"""
Services module — write-side business logic for the django_dirt_ratings app.

Following the Django Styleguide, services take keyword-only data arguments
(never a request), validate with ``full_clean``, and are the only layer that
writes to the database.
"""

import typing

from django.db import transaction
from django.db.models import F

from django_dirt_ratings import models, plan


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
    raw_metrics: dict | None = None,
    review_plan_id: int | None = None,
) -> models.Image:
    """Create the Image identified by its unique metadata, or refresh its bytes.

    The lookup fields are the ``image_meta`` unique constraint; updating in
    place preserves the primary key (hence any ratings) and ``priority``
    (recomputed by ``prioritize``), while refreshing the bytes, measures, and the
    plan the image was rendered under.
    """
    instance = models.Image.objects.filter(
        slice=slice, file1=file1, display=display, step=step
    ).first()
    if instance is None:
        instance = models.Image(slice=slice, file1=file1, display=display, step=step)
    instance.img = img
    instance.file2 = file2
    instance.raw_metrics = raw_metrics
    instance.review_plan_id = review_plan_id
    instance.full_clean(validate_unique=False)
    instance.save()
    return instance


class ImageRow(typing.TypedDict):
    """The fields of one Image as a plain row, for the upsert paths."""

    img: bytes
    file1: str
    file2: str | None
    display: int
    step: int
    slice: int | None
    # Omitting these matches Image(**row) semantics: the model defaults (None)
    # apply, which on conflict still refresh the stored values to NULL.
    raw_metrics: typing.NotRequired[dict | None]
    review_plan_id: typing.NotRequired[int | None]


def image_upsert_many(*, images: typing.Sequence[ImageRow]) -> None:
    """Create or refresh many Images in one INSERT ... ON CONFLICT.

    Each row holds the fields of one Image (``img``, ``file1``, ``file2``,
    ``display``, ``step``, ``slice``, ``raw_metrics``, ``review_plan_id``). On
    conflict against the ``image_meta`` unique key the bytes/measures/plan are
    refreshed in place, preserving the primary key (and hence ratings), ``n_reviews``
    and ``priority``. Only valid for non-null ``slice`` rows: SQLite treats NULLs as
    distinct in a unique index, so ON CONFLICT would not dedup them (the single-image
    DTIFIT step uses :func:`image_upsert` instead).
    """
    instances = [models.Image(**fields) for fields in images]
    for instance in instances:
        # Skip the unique/constraint checks — the image_meta uniqueness is what
        # ON CONFLICT resolves below (validate_constraints would reject the very
        # rows we intend to upsert). Field validation still runs.
        instance.full_clean(validate_unique=False, validate_constraints=False)
    models.Image.objects.bulk_create(
        instances,
        update_conflicts=True,
        unique_fields=["slice", "file1", "display", "step"],
        update_fields=["img", "file2", "raw_metrics", "review_plan"],
    )


def plan_apply(*, name: str, text: str) -> models.ReviewPlan:
    """Persist a review plan's TOML and make it the sole active plan.

    Idempotent by content: identical text reuses its :class:`models.ReviewPlan`
    row (dedup on ``content_hash``) and is simply re-activated. Editing the file
    makes a new row, so images/sessions stamped under the old plan keep their
    provenance.
    """
    digest = plan.content_hash(text)
    with transaction.atomic():
        record, _ = models.ReviewPlan.objects.get_or_create(
            content_hash=digest, defaults={"name": name, "toml": text}
        )
        models.ReviewPlan.objects.exclude(pk=record.pk).update(is_active=False)
        if not record.is_active:
            record.is_active = True
            record.save(update_fields=["is_active"])
    return record


def session_create(*, step: int, user: str | None = None) -> models.Session:
    # Pin the active plan's serving facet onto the session so ordering is stable for
    # its whole lifetime, even if the plan is re-applied mid-review.
    active = plan.active()
    session = models.Session(
        step=step,
        user=user,
        strategy=active.strategy,
    )
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
