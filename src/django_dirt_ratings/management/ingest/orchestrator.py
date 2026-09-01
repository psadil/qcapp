"""Drive discovery + rendering + writing for a whole dataset.

- **Discovery** runs in the parent: each spec's ``discover`` issues catalog
  queries + association lookups (no nibabel, no database), yielding lightweight
  :class:`RenderJob`\\ s.
- **Rendering** runs in a ``ProcessPoolExecutor`` (spawn): each worker loads a
  file's inputs once, runs the prep-once render, and returns every blob. CPU- and
  GIL-bound matplotlib work parallelizes across files; only paths in, blobs out.
- **Writing** happens back in the parent — the sole DB writer, since SQLite has a
  single writer — one call to ``services.unit_store`` per file, which lands the
  blobs in media storage and the rows (images + measurements) in the database.
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


def _measure(
    *, job: RenderJob, catalog: Mapping[str, Any] | None
) -> tuple[dict, dict[str, float | None]]:
    """Everything measured for one file: its categorical context, and the numbers.

    **Every** extractor whose input roles this job carries runs. The review plan
    chooses what to *order* by, never what to measure, so a metric DIRT can compute
    is computed and stored whether or not anything ranks on it — and a step that
    gains an input gains its metrics with no plan edit.

    Extraction runs here in the parent (the sole DB writer): each extractor loads
    only what it needs, cheap next to rendering. A failing extractor yields None
    for its own metrics rather than aborting the file.
    """
    entities: dict = dict(job.entities or {})
    values: dict[str, float | None] = {}
    for extractor in measures.MetricExtractor.applicable(job.inputs):
        try:
            produced = extractor.extract(job.inputs)
        except Exception:
            logger.exception(
                "measure %s failed for %s", type(extractor).__name__, job.file1
            )
            produced = extractor.unmeasured()
        values.update({str(name): value for name, value in produced.items()})
    for name, value in (catalog or {}).items():
        # A catalog value that is not a number is context to compare within, not a
        # measurement to rank; None is a measurement we could not pin down.
        if value is None or (
            not isinstance(value, bool) and isinstance(value, (int, float))
        ):
            values[name] = None if value is None else float(value)
        else:
            entities[name] = value
    return entities, values


def _write(
    *,
    step: models.Step,
    job: RenderJob,
    blobs: dict,
    catalog: Mapping[str, Any] | None,
    review_plan_id: int | None,
) -> None:
    entities, values = _measure(job=job, catalog=catalog)
    services.unit_store(
        step=int(step),
        file1=job.file1,
        file2=job.file2,
        entities=entities or None,
        values=values,
        review_plan_id=review_plan_id,
        blobs={(int(display), cut): data for (display, cut), data in blobs.items()},
    )


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

    # The active review plan stamps each image with its provenance
    # (Image.review_plan) and names any catalog measures. It no longer decides what
    # DIRT computes: every applicable extractor runs with or without a plan.
    record = plan.active_record()
    active = plan.parse(record.toml) if record is not None else plan.DEFAULT
    review_plan_id = record.id if record is not None else None
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
        rendered = set() if update else selectors.image_files_rendered(step=spec.step)
        for job in jobs:
            if job.file1 in rendered:
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
                catalog=catalog,
                review_plan_id=review_plan_id,
            )
            written += 1
            logger.info("wrote %s (%d/%d)", job.file1, written, len(pending))

    return written
