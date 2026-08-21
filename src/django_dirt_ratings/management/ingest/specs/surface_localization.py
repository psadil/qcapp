"""Surface-localization QC: the FreeSurfer white/pial ribbon over the brain volume.

FreeSurfer `recon-all` output is standardized but not BIDS, so it is indexed with
bidslake's FreeSurfer adapter (which catalogs the ``mri/*.mgz`` volumes) — mind
the anchor gotcha: a tree nested at ``sourcedata/freesurfer`` must be indexed as
its own dataset::

    bidslake index -i <...>/sourcedata/freesurfer --adapter freesurfer \\
        --dataset-id freesurfer -o study.duckdb

The volumes carry no BIDS entities in their names (``brain.mgz``, ``ribbon.mgz``
are fixed FreeSurfer filenames), and bidslake's concept columns are derived from
the path, so we pair them by their filename and subject rather than by a BIDS
suffix.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import render
from ..registry import RenderJob, StepSpec, register

_VOLUMES = {"brain.mgz": "brain", "ribbon.mgz": "ribbon"}


def discover(lake: Any, filters: dict[str, Any]) -> list[RenderJob]:
    # Gather the brain/ribbon volumes, keyed by subject (+ session).
    by_subject: dict[tuple, dict[str, Any]] = defaultdict(dict)
    for f in lake.get(extension=".mgz", **filters):
        role = _VOLUMES.get(Path(f.file_path).name)
        if role is None:
            continue
        by_subject[(f.entities.get("sub"), f.entities.get("ses"))][role] = f

    jobs: list[RenderJob] = []
    for pair in by_subject.values():
        ribbon, brain = pair.get("ribbon"), pair.get("brain")
        if ribbon is None or brain is None:
            continue
        jobs.append(
            RenderJob(
                file1=ribbon.file_path,
                file2=brain.file_path,
                render_key="surface_localization",
                inputs={
                    "ribbon": str(ribbon.local_path),
                    "brain": str(brain.local_path),
                },
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
