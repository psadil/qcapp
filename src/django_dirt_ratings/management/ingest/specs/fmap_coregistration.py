"""Field-map coregistration QC: the reference EPI and the coregistered boldref,
each masked, animated so the reviewer can flip between them.

This is where the old string-surgery was worst. bidslake resolves every related
file by BIDS concept instead: the reference EPI by an entity swap, the
``IntendedFor`` bold targets from the merged sidecar, and each target's boldref /
brain mask / boldref->fieldmap transform by entity query — including the correct
``to-auto#####`` transform (the old code guessed ``auto00001``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids, render
from ..registry import RenderJob, StepSpec, register

_TARGET_ENTITIES = ("sub", "ses", "task", "run", "acq")


def discover(lake: Any, filters: dict[str, Any]) -> list[RenderJob]:
    query = {
        "datatype": "fmap",
        "suffix": "fieldmap",
        "desc": "preproc",
        "extension": ".nii.gz",
        **filters,
    }
    jobs: list[RenderJob] = []
    for fmap in lake.get(**query):
        e = fmap.entities
        epi = bids.first(
            lake,
            datatype="fmap",
            suffix="fieldmap",
            desc="epi",
            sub=e.get("sub"),
            ses=e.get("ses"),
            run=e.get("run"),
            acq=e.get("acq"),
            extension=".nii.gz",
        )
        if epi is None:
            continue
        for target in bids.intended_for(fmap.metadata):
            bold = bids.parse_entities(target)
            shared = {k: bold.get(k) for k in _TARGET_ENTITIES}
            boldref = bids.first(
                lake,
                datatype="func",
                suffix="boldref",
                desc="coreg",
                extension=".nii.gz",
                **shared,
            )
            mask = bids.first(
                lake,
                datatype="func",
                suffix="mask",
                desc="brain",
                space=None,
                extension=".nii.gz",
                **shared,
            )
            xfm = bids.first(
                lake, datatype="func", suffix="xfm", extension=".txt", **shared
            )
            if not (boldref and mask and xfm):
                continue
            jobs.append(
                RenderJob(
                    file1=Path(boldref.file_path).name,
                    file2=Path(epi.file_path).name,
                    render_key="fmap_coregistration",
                    inputs={
                        "epi": str(epi.local_path),
                        "boldref": str(boldref.local_path),
                        "mask": str(mask.local_path),
                        "transform": str(xfm.local_path),
                    },
                    cuts=list(range(render.N_CUTS)),
                    displays=list(models.DisplayMode),
                )
            )
    return jobs


register(
    StepSpec(
        step=models.Step.FMAP_COREGISTRATION,
        name="fmap_coregistration",
        discover=discover,
    )
)
