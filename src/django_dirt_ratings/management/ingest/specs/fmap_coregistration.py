"""Field-map coregistration QC: the reference EPI and the coregistered boldref,
each masked, animated so the reviewer can flip between them.

This is where the old string-surgery was worst. bidslake resolves every related
file by BIDS concept instead: the reference EPI by an entity swap, the
``IntendedFor`` bold targets from the merged sidecar, and each target's boldref /
brain mask / boldref->fieldmap transform by entity query — including the correct
``to-auto#####`` transform (the old code guessed ``auto00001``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids, render
from ..registry import RenderJob, StepSpec, register

_TARGET_ENTITIES = ("sub", "ses", "task", "run", "acq")
_EPI_KEY = ("sub", "ses", "run", "acq")


def discover(lake: Any, filters: Mapping[str, Any]) -> list[RenderJob]:
    query = {
        "datatype": "fmap",
        "suffix": "fieldmap",
        "desc": "preproc",
        "extension": ".nii.gz",
        **filters,
    }
    fmaps = list(lake.get(**query))
    if not fmaps:
        return []
    # One indexing query per role instead of 1 + 3-per-IntendedFor-target
    # lookups per fieldmap. The `IntendedFor` link itself must come from the
    # merged sidecar (the catalog's fieldmap associations carry no resolved
    # target ids), so targets stay parsed from metadata below.
    epis = bids.index_by(
        lake,
        _EPI_KEY,
        datatype="fmap",
        suffix="fieldmap",
        desc="epi",
        extension=".nii.gz",
    )
    boldrefs = bids.index_by(
        lake,
        _TARGET_ENTITIES,
        datatype="func",
        suffix="boldref",
        desc="coreg",
        extension=".nii.gz",
    )
    masks = bids.index_by(
        lake,
        _TARGET_ENTITIES,
        datatype="func",
        suffix="mask",
        desc="brain",
        space=None,
        extension=".nii.gz",
    )
    # `desc=None` pins the boldref->fieldmap alignment: a full fMRIPrep run also
    # writes `desc-coreg` (boldref->T1w) and `desc-hmc` transforms with the same
    # entities, which would otherwise make every key ambiguous.
    xfms = bids.index_by(
        lake,
        _TARGET_ENTITIES,
        datatype="func",
        suffix="xfm",
        desc=None,
        extension=".txt",
    )
    jobs: list[RenderJob] = []
    for fmap in fmaps:
        e = fmap.entities
        epi = epis.get(tuple(e.get(k) for k in _EPI_KEY))
        if epi is None:
            continue
        for target in bids.intended_for(fmap.metadata):
            bold = bids.parse_entities(target)
            shared = {k: bold.get(k) for k in _TARGET_ENTITIES}
            key = tuple(shared.values())
            boldref = boldrefs.get(key)
            mask = masks.get(key)
            xfm = xfms.get(key)
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
                    # The BOLD run's identity, so a cross-dataset catalog measure (an
                    # MRIQC bold IQM in a sibling dataset) can be paired by entity.
                    source_dataset_id=boldref.dataset_id,
                    source_entities=dict(shared),
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
