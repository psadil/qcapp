import functools
import logging
import typing as t
from pathlib import Path

import nibabel as nb
import polars as pl
import typer
from django_typer.completers import path
from django_typer.management import TyperCommand

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
        res: t.Annotated[
            str | None,
            typer.Option(
                help="Filter to a specific resolution (e.g. '2'). "
                "By default, all resolutions are included.",
            ),
        ] = None,
        update: t.Annotated[
            bool, typer.Option(help="Whether to update img in database")
        ] = False,
    ):
        """
        Add Masks from BIDS Table
        """

        df = pl.read_parquet(index).filter(
            pl.col("datatype") == "anat",
            pl.col("desc") == "brain",
        )
        if res is not None:
            df = df.filter(pl.col("res") == res)

        masks: list[str] = (
            df
            .with_columns(masks=pl.col("root") + "/" + pl.col("path"))
            .select("masks")
            .to_series()
            .to_list()
        )

        anats = [x.replace("desc-brain_mask", "desc-preproc_T1w") for x in masks]

        for mask, anat in zip(masks, anats):
            logging.info(f"{mask=}")
            if not Path(anat).exists():
                anat = mask.replace("desc-brain_mask", "T1w")
            mask_nii = nb.nifti1.Nifti1Image.load(mask)
            file_nii = nb.nifti1.Nifti1Image.load(anat)
            _ingest.ingest_series(
                file1=Path(mask).name,
                file2=Path(anat).name,
                step=models.Step.MASK,
                cuts=range(_render.N_CUTS),
                render=functools.partial(
                    _render.get_mask, mask_nii=mask_nii, file_nii=file_nii
                ),
                update=update,
            )
