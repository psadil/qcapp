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
# The anatomical derivatives a whole session shares, for the coverage measures.
_ANAT_KEY = ("sub", "ses")


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
    # `to-auto#####` pins the boldref->fieldmap alignment: a full fMRIPrep run
    # also writes a boldref->T1w transform with the same entities, which would
    # otherwise make every key ambiguous. Keyed off `from`/`to` rather than
    # `desc`, which is absent on older fMRIPrep but `desc-fmap` on v4+.
    xfms = bids.index_by(
        lake,
        _TARGET_ENTITIES,
        where=lambda f: str(f.entities.get("to") or "").startswith("auto"),
        datatype="func",
        suffix="xfm",
        extension=".txt",
        **{"from": "boldref"},  # `from` is a keyword, so it cannot be a kwarg
    )
    # The session's anatomical segmentation and the boldref->T1w affine. Together
    # they say how much of each structure this run's field of view missed: the T1w
    # covers the whole head, so its aseg knows each structure's true extent. All
    # three or none — a segmentation with no way into this run's frame measures
    # nothing here.
    asegs = bids.index_by(
        lake,
        _ANAT_KEY,
        datatype="anat",
        suffix="dseg",
        desc="aseg",
        extension=".nii.gz",
    )
    # The label lookup is a dataset-root file with no subject entities (BIDS
    # inheritance), so it is keyed by the tree it sits at the top of.
    aseg_labels = bids.index_by(
        lake,
        ("root_uri",),
        suffix="dseg",
        desc="aseg",
        extension=".tsv",
    )
    # `from` is a keyword, so this pair cannot be spelled as kwargs.
    boldref_to_anat: dict[str, Any] = {"from": "boldref", "to": "T1w"}
    anat_xfms = bids.index_by(
        lake,
        _TARGET_ENTITIES,
        datatype="func",
        suffix="xfm",
        extension=".txt",
        **boldref_to_anat,
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
            inputs = {
                "epi": str(epi.local_path),
                "boldref": str(boldref.local_path),
                "mask": str(mask.local_path),
                "transform": str(xfm.local_path),
            }
            anat_key = tuple(bold.get(k) for k in _ANAT_KEY)
            aseg = asegs.get(anat_key)
            labels = aseg_labels.get((aseg.root_uri,)) if aseg else None
            anat_xfm = anat_xfms.get(key)
            if aseg and labels and anat_xfm:
                inputs["dseg"] = str(aseg.local_path)
                inputs["dseg_labels"] = str(labels.local_path)
                inputs["boldref2anat"] = str(anat_xfm.local_path)
            jobs.append(
                RenderJob(
                    file1=Path(boldref.file_path).name,
                    file2=Path(epi.file_path).name,
                    render_key="fmap_coregistration",
                    inputs=inputs,
                    cuts=list(range(render.COREG_N_CUTS)),
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
