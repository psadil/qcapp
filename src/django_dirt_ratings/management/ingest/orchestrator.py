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

from django_dirt_ratings import models, selectors, services

from . import render
from . import specs as _specs  # noqa: F401  (import registers every StepSpec)
from ._worker import init_django
from .registry import STEP_SPECS, RenderJob

logger = logging.getLogger(__name__)


def _write(*, step: models.Step, job: RenderJob, blobs: dict) -> None:
    rows = [
        {
            "img": data,
            "file1": job.file1,
            "file2": job.file2,
            "display": int(display),
            "step": int(step),
            "slice": cut,
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
            _write(step=step, job=job, blobs=blobs)
            written += 1
            logger.info("wrote %s (%d/%d)", job.file1, written, len(pending))

    return written
