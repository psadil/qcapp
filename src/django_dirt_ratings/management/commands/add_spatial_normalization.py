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

N_SPATIAL_NORMALIZATION_CUTS = 3


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
        Add spatial normalization figures from BIDS Table
        """

        df = pl.read_parquet(index).filter(
            pl.col("datatype") == "anat",
            pl.col("desc") == "preproc",
            pl.col("space") == "MNI152NLin2009cAsym",
        )
        if res is not None:
            df = df.filter(pl.col("res") == res)

        anats: list[str] = (
            df.with_columns(anat=pl.col("root") + "/" + pl.col("path"))
            .select("anat")
            .to_series()
            .to_list()
        )

        for anat in anats:
            logging.info(f"{anat=}")
            file_nii = nb.nifti1.Nifti1Image.load(anat)
            _ingest.ingest_series(
                file1=Path(anat).name,
                step=models.Step.SPATIAL_NORMALIZATION,
                cuts=range(N_SPATIAL_NORMALIZATION_CUTS),
                render=functools.partial(
                    _render.get_spatial_normalization, file_nii=file_nii
                ),
                update=update,
            )
