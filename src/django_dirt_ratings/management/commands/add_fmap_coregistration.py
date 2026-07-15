import functools
import json
import logging
import typing as t
from pathlib import Path

import nibabel as nb
import nitransforms as nt
import polars as pl
import typer
from django_typer.completers import path
from django_typer.management import TyperCommand
from nibabel import spatialimages

from django_dirt_ratings import models

from . import _ingest, _render


class Command(TyperCommand):
    def handle(
        self,
        index: t.Annotated[
            Path,
            typer.Argument(
                file_okay=True,
                exists=True,
                dir_okay=False,
                readable=True,
                shell_complete=path.paths,
            ),
        ],
        update: t.Annotated[
            bool, typer.Option(help="Whether to update img in database")
        ] = False,
    ):
        """
        Add fmap coregistration figures from BIDS Table
        """

        fieldmaps = pl.read_parquet(index).filter(
            pl.col("datatype") == "fmap", pl.col("desc") == "preproc"
        )

        for fieldmap in fieldmaps.iter_rows(named=True):
            logging.info(f"{fieldmap=}")
            root = Path(fieldmap.get("root", ""))
            path: str = fieldmap.get("path", "")
            sidecar: dict = json.loads(
                (root / path.replace(".nii.gz", ".json")).read_text()
            )
            file2 = root / path.replace("preproc", "epi")
            file2_nii = nb.nifti1.Nifti1Image.load(file2)
            intendedfor: list[str] = sidecar.get("IntendedFor")  # type:ignore
            if not intendedfor:
                logging.info("No IntendedFor field found. Skipping.")
                continue
            for i in intendedfor:
                logging.info(f"{i=}")
                mask = (
                    root
                    / f"sub-{fieldmap.get('sub')}"
                    / i.replace("_bold", "_desc-brain_mask")
                )
                boldref = (
                    root
                    / f"sub-{fieldmap.get('sub')}"
                    / i.replace("_bold", "_desc-coreg_boldref")
                )
                transform_file = boldref.parent / boldref.name.replace(
                    "desc-coreg_boldref.nii.gz",
                    "from-boldref_to-auto00001_mode-image_xfm.txt",
                )
                if not (mask.exists() and boldref.exists() and transform_file.exists()):
                    logging.info("missing file. skipping.")
                    continue
                transform = nt.linear.load(transform_file, reference=file2_nii)
                mask_nii: spatialimages.SpatialImage = nt.resampling.apply(
                    transform, spatialimage=mask, order=0
                )  # type: ignore
                # sometimes, the boldref is stored as a 4d image (even though
                # the fourth dimension has only length 1)
                boldref_nii = nb.funcs.squeeze_image(
                    nb.nifti1.Nifti1Image.load(boldref)
                )
                file_nii: spatialimages.SpatialImage = nt.resampling.apply(
                    transform, spatialimage=boldref_nii
                )  # type: ignore
                _ingest.ingest_series(
                    file1=boldref.name,
                    file2=file2.name,
                    step=models.Step.FMAP_COREGISTRATION,
                    cuts=range(_render.N_CUTS),
                    render=functools.partial(
                        _render.get_fmap_coregistration,
                        mask_nii=mask_nii,
                        file_nii=file_nii,
                        file2_nii=file2_nii,
                    ),
                    update=update,
                )
