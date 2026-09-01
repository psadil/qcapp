"""
Services module — write-side business logic for the django_dirt_ratings app.

Following the Django Styleguide, services take keyword-only data arguments
(never a request), validate with ``full_clean``, and are the only layer that
writes to the database.
"""

import typing
from collections.abc import Mapping

from django.db import transaction
from django.db.models import F

from django_dirt_ratings import models, plan, storage


def image_create(
    *,
    img: bytes,
    file1: str,
    display: int,
    step: int,
    slice: int | None = None,
    file2: str | None = None,
) -> models.Image:
    digest = storage.image_digest(img)
    name = storage.image_name(
        step=step, file1=file1, display=display, slice=slice, digest=digest
    )
    storage.save(name, img)
    instance = models.Image(
        img=name,
        digest=digest,
        file1=file1,
        display=display,
        step=step,
        slice=slice,
        file2=file2,
    )
    instance.full_clean()
    instance.save()
    return instance


def image_delete(*, image: models.Image) -> None:
    name = image.img.name
    image.delete()
    if name:
        storage.delete(name)


def image_upsert(
    *,
    img: str,
    digest: str,
    file1: str,
    display: int,
    step: int,
    slice: int | None = None,
    file2: str | None = None,
    review_plan_id: int | None = None,
) -> models.Image:
    """Create the Image identified by its unique metadata, or repoint its file.

    ``img`` is a storage name (see :mod:`~django_dirt_ratings.storage`), not
    bytes — writing the file is the caller's job, so this stays usable from
    both the local render path and the upload API. The lookup fields are the
    ``image_meta`` unique constraint; updating in place preserves the primary
    key (hence any ratings) and ``priority`` (recomputed by ``prioritize``).
    Measurements live on :class:`models.MeasuredFile`.
    """
    instance = models.Image.objects.filter(
        slice=slice, file1=file1, display=display, step=step
    ).first()
    if instance is None:
        instance = models.Image(slice=slice, file1=file1, display=display, step=step)
    instance.img = img
    instance.digest = digest
    instance.file2 = file2
    instance.review_plan_id = review_plan_id
    instance.full_clean(validate_unique=False)
    instance.save()
    return instance


class ImageRow(typing.TypedDict):
    """The fields of one Image as a plain row, for the upsert paths."""

    img: str
    digest: str
    file1: str
    file2: str | None
    display: int
    step: int
    slice: int | None
    # Omitting this matches Image(**row) semantics: the model default (None)
    # applies, which on conflict still refreshes the stored value to NULL.
    review_plan_id: typing.NotRequired[int | None]


def image_upsert_many(*, images: typing.Sequence[ImageRow]) -> None:
    """Create or refresh many Images in one INSERT ... ON CONFLICT.

    Each row holds the fields of one Image (``img`` — a storage name — plus
    ``digest``, ``file1``, ``file2``, ``display``, ``step``, ``slice``,
    ``review_plan_id``). On conflict against the ``image_meta`` unique key the
    file reference and plan are refreshed in place, preserving the primary key
    (and hence ratings), ``n_reviews`` and ``priority``. Only valid for
    non-null ``slice`` rows: SQLite treats NULLs as distinct in a unique index,
    so ON CONFLICT would not dedup them (the single-image DTIFIT step uses
    :func:`image_upsert` instead).
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
        update_fields=["img", "digest", "file2", "review_plan"],
    )


class ImageRef(typing.TypedDict):
    """One image of a unit: its view identity and content digest — no bytes."""

    display: int
    slice: int | None
    digest: str


def unit_upsert_rows(
    *,
    step: int,
    file1: str,
    file2: str | None,
    entities: dict | None,
    values: typing.Mapping[str, float | None],
    review_plan_id: int | None,
    images: typing.Sequence[ImageRef],
) -> list[str]:
    """Upsert one measured file and its image rows; return replaced storage names.

    The row-side half of storing a unit, shared by the local render path
    (:func:`unit_store`) and the upload API — files are the caller's concern.
    A returned name is one an updated row used to point at (its digest
    changed): safe to delete only *after* this returns, never before, because
    until then it is what reviewers are still being served.
    """
    existing = {
        (display, cut): (name, digest)
        for display, cut, name, digest in models.Image.objects.filter(
            step=step, file1=file1
        ).values_list("display", "slice", "img", "digest")
    }
    rows: list[ImageRow] = [
        {
            "img": storage.image_name(
                step=step,
                file1=file1,
                display=ref["display"],
                slice=ref["slice"],
                digest=ref["digest"],
            ),
            "digest": ref["digest"],
            "file1": file1,
            "file2": file2,
            "display": ref["display"],
            "step": step,
            "slice": ref["slice"],
            "review_plan_id": review_plan_id,
        }
        for ref in images
    ]
    with transaction.atomic():
        measured_file_upsert(
            step=step,
            file1=file1,
            entities=entities,
            values=values,
            review_plan_id=review_plan_id,
        )
        # NULL-slice rows (single-image DTIFIT) can't use ON CONFLICT; the rest batch.
        if any(row["slice"] is None for row in rows):
            for row in rows:
                image_upsert(**row)
        else:
            image_upsert_many(images=rows)
    replaced = []
    for ref in images:
        previous = existing.get((ref["display"], ref["slice"]))
        if previous is not None and previous[0] and previous[1] != ref["digest"]:
            replaced.append(previous[0])
    return replaced


def unit_store(
    *,
    step: int,
    file1: str,
    file2: str | None,
    entities: dict | None,
    values: typing.Mapping[str, float | None],
    review_plan_id: int | None,
    blobs: Mapping[tuple[int, int | None], bytes],
) -> int:
    """Store one unit locally: files into media, rows into the database.

    Files are written before rows and replaced files deleted only after the
    rows point away — a failure partway leaves unreachable orphans (reclaimed
    by ``manage prune_media``), never a page of broken images. Idempotent:
    unchanged bytes keep their digest, so nothing is rewritten.
    """
    current = {
        (display, cut): digest
        for display, cut, digest in models.Image.objects.filter(
            step=step, file1=file1
        ).values_list("display", "slice", "digest")
    }
    refs: list[ImageRef] = []
    for (display, cut), data in blobs.items():
        digest = storage.image_digest(data)
        refs.append({"display": display, "slice": cut, "digest": digest})
        name = storage.image_name(
            step=step, file1=file1, display=display, slice=cut, digest=digest
        )
        # The exists() check covers a wiped media/ next to a surviving database.
        if current.get((display, cut)) != digest or not storage.exists(name):
            storage.save(name, data)
    replaced = unit_upsert_rows(
        step=step,
        file1=file1,
        file2=file2,
        entities=entities,
        values=values,
        review_plan_id=review_plan_id,
        images=refs,
    )
    for name in replaced:
        storage.delete(name)
    return len(refs)


def measured_file_upsert(
    *,
    step: int,
    file1: str,
    entities: dict | None = None,
    values: typing.Mapping[str, float | None] | None = None,
    review_plan_id: int | None = None,
) -> models.MeasuredFile:
    """Record one file's measurements, replacing whatever was measured before.

    The measured set is authoritative: a metric that used to be stored for this
    file and is not in ``values`` is deleted, so dropping an extractor (or a
    catalog measure leaving the plan) does not leave a stale number behind for
    ``prioritize`` to rank on. A ``None`` value is kept, and means something
    different from absence — the extractor ran and could not measure this file.
    """
    rows = {str(name): value for name, value in (values or {}).items()}
    with transaction.atomic():
        instance, _ = models.MeasuredFile.objects.get_or_create(step=step, file1=file1)
        instance.entities = entities
        instance.review_plan_id = review_plan_id
        instance.full_clean(validate_unique=False)
        instance.save()
        instance.metrics.exclude(name__in=list(rows)).delete()
        metrics = [
            models.Metric(file=instance, name=name, value=value)
            for name, value in rows.items()
        ]
        for metric in metrics:
            metric.full_clean(validate_unique=False, validate_constraints=False)
        models.Metric.objects.bulk_create(
            metrics,
            update_conflicts=True,
            unique_fields=["file", "name"],
            update_fields=["value"],
        )
    return instance


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
