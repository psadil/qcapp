"""Surface-localization QC: the FreeSurfer white/pial ribbon over the brain volume.

Depends on the ``freesurfer`` bidslake adapter (Phase 2d), extended to catalog
the ``mri/brain.mgz`` and ``mri/ribbon.mgz`` volumes (the stock adapter projects
only the tabular ``stats`` outputs). Note the anchor behavior: a FreeSurfer tree
nested at ``sourcedata/freesurfer`` must be indexed as its own dataset
(``bidslake index --input <...>/sourcedata/freesurfer --adapter freesurfer``).
Until the volumes are cataloged, ``discover`` yields no jobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids, render
from ..registry import RenderJob, StepSpec, register


def discover(lake: Any, filters: dict[str, Any]) -> list[RenderJob]:
    jobs: list[RenderJob] = []
    for ribbon in lake.get(suffix="ribbon", extension=".mgz", **filters):
        e = ribbon.entities
        brain = bids.first(
            lake, suffix="brain", extension=".mgz", sub=e.get("sub"), ses=e.get("ses")
        )
        if brain is None:
            continue
        jobs.append(
            RenderJob(
                file1=Path(ribbon.file_path).name,
                file2=Path(brain.file_path).name,
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
