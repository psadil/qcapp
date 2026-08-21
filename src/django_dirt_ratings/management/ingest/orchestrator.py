"""Drive discovery + rendering + writing for a whole dataset.

- **Discovery** runs in the parent: each spec's ``discover`` issues catalog
  queries + association lookups (no nibabel, no database), yielding lightweight
  :class:`RenderJob`\\ s.
- **Rendering** runs in a ``ProcessPoolExecutor`` (spawn): each worker loads a
  file's inputs once, runs the prep-once render, and returns every blob. CPU- and
  GIL-bound matplotlib work parallelizes across files; only paths in, blobs out.
- **Writing** happens back in the parent — the sole DB writer, since SQLite has a
  single writer — batched per file via ``services.image_upsert_many``.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

from django_dirt_ratings import models, plan, selectors, services

from . import harvest, measures, render
from . import specs as _specs  # noqa: F401  (import registers every StepSpec)
from ._worker import init_django
from .registry import STEP_SPECS, RenderJob

logger = logging.getLogger(__name__)

# A resolved computed measure: (raw_metrics key, extractor instance).
_Extractor = tuple[str, measures.MetricExtractor]


def _measure(*, job: RenderJob, extractors: Sequence[_Extractor]) -> dict | None:
    """Merge catalog-derived job metrics with the computed extractor values.

    Extraction runs here in the parent (the sole DB writer): each extractor loads
    only what it needs, cheap next to rendering. A failing extractor yields None
    rather than aborting the file.
    """
    values: dict = dict(job.metrics or {})
    for name, extractor in extractors:
        try:
            values[name] = extractor.extract(job.inputs)
        except Exception:
            logger.exception("measure %r failed for %s", name, job.file1)
            values[name] = None
    return values or None


def _write(
    *,
    step: models.Step,
    job: RenderJob,
    blobs: dict,
    extractors: Sequence[_Extractor],
    catalog: Mapping[str, Any] | None,
    review_plan_id: int | None,
) -> None:
    raw = _measure(job=job, extractors=extractors)
    if catalog:
        raw = {**(raw or {}), **catalog}
    rows: list[services.ImageRow] = [
        {
            "img": data,
            "file1": job.file1,
            "file2": job.file2,
            "display": int(display),
            "step": int(step),
            "slice": cut,
            "raw_metrics": raw,
            "review_plan_id": review_plan_id,
        }
        for (display, cut), data in blobs.items()
    ]
    # NULL-slice rows (single-image DTIFIT) can't use ON CONFLICT; the rest batch.
    if any(row["slice"] is None for row in rows):
        for row in rows:
            services.image_upsert(**row)
    else:
        services.image_upsert_many(images=rows)


def ingest_dataset(
    *,
    lake: Any,
    steps: Sequence[str] | None = None,
    filters: Mapping[str, Any] | None = None,
    update: bool = False,
    workers: int | None = None,
) -> int:
    """Render every discovered job for the chosen steps; return files written."""
    filters = dict(filters or {})
    chosen = [STEP_SPECS[s] for s in steps] if steps else list(STEP_SPECS.values())

    # The active review plan drives which measures to compute and stamps each image
    # with its provenance (Image.review_plan). No plan → no measures, breadth-first.
    record = plan.active_record()
    active = plan.parse(record.toml) if record is not None else plan.DEFAULT
    review_plan_id = record.id if record is not None else None
    extractors_by_step: dict[models.Step, list[_Extractor]] = {
        sp.step: [
            (m.name, measures.MetricExtractor.get(m.compute))
            for m in sp.computed_measures
            if m.compute  # always true (computed_measures filters); narrows the type
        ]
        for sp in active.steps
    }
    # Cross-dataset catalog measures (an MRIQC IQM in a sibling dataset), harvested
    # per job from the live lake in the loop below.
    catalog_by_step: dict[models.Step, list[plan.Measure]] = {
        sp.step: [m for m in sp.catalog_measures if m.is_cross_dataset]
        for sp in active.steps
    }

    pending: list[tuple[models.Step, RenderJob]] = []
    for spec in chosen:
        jobs = spec.discover(lake, filters)
        logger.info("step %s: discovered %d job(s)", spec.name, len(jobs))
        for job in jobs:
            if not update and selectors.image_file_exists(
                file1=job.file1, step=spec.step
            ):
                continue
            pending.append((spec.step, job))

    if not pending:
        logger.info("nothing to render")
        return 0

    written = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx, initializer=init_django
    ) as executor:
        futures = {
            executor.submit(
                render.render_job,
                render_key=job.render_key,
                inputs=job.inputs,
                cuts=list(job.cuts),
                displays_=list(job.displays),
            ): (step, job)
            for step, job in pending
        }
        for future in as_completed(futures):
            step, job = futures[future]
            try:
                blobs = future.result()
            except Exception:
                logger.exception("render failed: %s (%s)", job.file1, job.render_key)
                continue
            # A harvest failure (e.g. a catalog predating cross-dataset links,
            # where bidslake raises RuntimeError) degrades to no catalog
            # metrics rather than aborting the run mid-loop.
            try:
                catalog = harvest.harvest_catalog(
                    lake,
                    job.source_dataset_id,
                    job.source_entities,
                    catalog_by_step.get(step, []),
                )
            except RuntimeError:
                logger.exception("catalog harvest failed for %s", job.file1)
                catalog = {}
            _write(
                step=step,
                job=job,
                blobs=blobs,
                extractors=extractors_by_step.get(step, []),
                catalog=catalog,
                review_plan_id=review_plan_id,
            )
            written += 1
            logger.info("wrote %s (%d/%d)", job.file1, written, len(pending))

    return written
