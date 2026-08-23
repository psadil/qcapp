"""Surface-localization QC: the FreeSurfer white/pial ribbon over the brain volume.

FreeSurfer `recon-all` output is standardized but not BIDS, so it is indexed with
bidslake's FreeSurfer adapter (which catalogs the ``mri/*.mgz`` volumes) — mind
the anchor gotcha: a tree nested at ``sourcedata/freesurfer`` must be indexed as
its own dataset::

    bidslake index -i <...>/sourcedata/freesurfer --adapter freesurfer \\
        --dataset-id freesurfer -o study.duckdb

The volumes carry no BIDS entities in their names (``brain.mgz``, ``ribbon.mgz``
are fixed FreeSurfer filenames, and their catalog rows have no concept columns),
so the pairing is one self-join on subject/session with the two path suffixes —
one query for the whole study.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from django_dirt_ratings import models

from .. import lake as lake_mod
from .. import render
from ..registry import Lake, RenderJob, StepSpec, register

logger = logging.getLogger(__name__)


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    rows = lake_mod.unit_rows(
        lake,
        anchor={"extension": ".mgz", **filters},
        anchor_basename="mri/ribbon.mgz",
        # FreeSurfer's bundled fsaverage tree is indexed subject-less; without
        # this it would masquerade as one reviewable "subject". (Verified on the
        # a2cps catalog: every NULL-sub brain/ribbon row is an fsaverage path;
        # the adapter parses `sub` from real subject directories.)
        require=("sub",),
        entities=("sub", "ses"),
        roles={
            "brain": lake_mod.Role(
                join=("dataset_id", "sub", "ses"),
                where={"extension": ".mgz"},
                basename="mri/brain.mgz",
            ),
        },
    )
    return _jobs_from_rows(rows)


def _jobs_from_rows(rows: list[lake_mod.UnitRow]) -> list[RenderJob]:
    """Turn resolved ribbon rows into jobs, deduping repeated index runs.

    The same physical FreeSurfer tree can be indexed twice — as its own
    dataset and again under the fMRIPrep dataset's sourcedata/. Rows whose
    ribbons resolve to one absolute path are one file, not an ambiguity: keep
    the row whose dataset roots the tree directly (the shortest catalog
    path). Genuinely distinct ribbons for one (sub, ses) — including
    subject-less rows sharing the (None, None) key — are skipped loudly,
    never merged.
    """
    by_subject: dict[tuple, list[lake_mod.UnitRow]] = defaultdict(list)
    for row in rows:
        by_subject[(row.entities["sub"], row.entities["ses"])].append(row)

    jobs: list[RenderJob] = []
    for (sub, ses), candidates in by_subject.items():
        resolved = [r for r in candidates if not r.unresolved]
        if not resolved:
            candidates[0].warn_unresolved(logger)
            continue
        # realpath, not normpath: index runs may reach one tree through symlinks.
        distinct = {os.path.realpath(r.local) for r in resolved}
        if len(distinct) > 1:
            logger.warning(
                "skipping sub-%s ses-%s: %d distinct ribbon volumes",
                sub,
                ses,
                len(distinct),
            )
            continue
        row = min(resolved, key=lambda r: len(r.file_path))
        brain = row.roles["brain"]
        if brain is None:  # resolved rows have every role; narrows the type
            continue
        jobs.append(
            RenderJob(
                file1=row.file_path,
                file2=brain.file_path,
                render_key="surface_localization",
                inputs={"ribbon": row.local, "brain": brain.local},
                cuts=list(range(render.N_CUTS)),
                displays=list(models.DisplayMode),
            )
        )
    return jobs


register(
    StepSpec(
        step=models.Step.SURFACE_LOCALIZATION,
        name="surface_localization",
        discover=discover,
    )
)
