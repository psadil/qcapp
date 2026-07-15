import functools
import logging
import typing as t
from pathlib import Path

import typer
from django_typer.completers import path
from django_typer.management import TyperCommand

from django_dirt_ratings import models

from . import _ingest, _render


class Command(TyperCommand):
    def handle(
        self,
        subjects_dir: t.Annotated[
            Path,
            typer.Argument(
                file_okay=False,
                exists=True,
                dir_okay=True,
                readable=True,
                shell_complete=path.paths,
            ),
        ],
        include: t.Annotated[list[str] | None, typer.Option()] = None,
        exclude: t.Annotated[list[str] | None, typer.Option()] = None,
        update: t.Annotated[
            bool, typer.Option(help="Whether to update img in database")
        ] = False,
    ):
        """
        Add surface localization figures
        """

        for sub in subjects_dir.glob("*"):
            if include and sub.name not in include:
                logging.info(
                    f"--include specified but {sub.name} not in list. Excluding"
                )
                continue
            if exclude and sub.name in exclude:
                logging.info(f"--exclude specified and {sub.name} in list. Excluding")
                continue
            brain_mgz = sub / "mri" / "brain.mgz"
            ribbon_mgz = sub / "mri" / "ribbon.mgz"

            if not brain_mgz.exists() or not ribbon_mgz.exists():
                logging.info(
                    f"Missing brain.mgz or ribbon.mgz for {sub.name}. Skipping."
                )
                continue

            brain_nii = _render.mgz_to_nifti(brain_mgz)
            ribbon_nii = _render.mgz_to_nifti(ribbon_mgz)
            _ingest.ingest_series(
                file1=str(ribbon_mgz.relative_to(subjects_dir)),
                file2=str(brain_mgz.relative_to(subjects_dir)),
                step=models.Step.SURFACE_LOCALIZATION,
                cuts=range(_render.N_CUTS),
                render=functools.partial(
                    _render.get_surface_localization,
                    brain_nii=brain_nii,
                    ribbon_nii=ribbon_nii,
                ),
                update=update,
            )
