import asyncio
import logging
import typing as t
from pathlib import Path

import typer
from django_typer.completers import path
from django_typer.management import TyperCommand


from django_dirt_ratings import models

from . import _private


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
                logging.info(f"Missing brain.mgz or ribbon.mgz for {sub.name}. Skipping.")
                continue

            brain_nii = _private.mgz_to_nifti(brain_mgz)
            ribbon_nii = _private.mgz_to_nifti(ribbon_mgz)
            file1 = str(ribbon_mgz.relative_to(subjects_dir))
            logging.info(f"{file1=}")
            for display_mode in models.DisplayMode.choices:
                logging.info(f"{display_mode=}")
                for cut in range(_private.N_CUTS):
                    logging.info(f"{cut=}")
                    if models.Image.objects.filter(
                        slice=cut,
                        display=display_mode[0],
                        step=models.Step.SURFACE_LOCALIZATION,
                        file1=file1,
                    ).exists():
                        logging.info("Found object. Skipping")
                        continue

                    i = _private.get_surface_localization(
                        cut=cut,
                        display_mode=models.DisplayMode(display_mode[0]),
                        brain_nii=brain_nii,
                        ribbon_nii=ribbon_nii,
                    )
                    asyncio.run(
                        models.Image.objects.acreate(
                            img=i,
                            slice=cut,
                            display=display_mode[0],
                            step=models.Step.SURFACE_LOCALIZATION,
                            file1=file1,
                            file2=str(brain_mgz.relative_to(subjects_dir)),
                        )
                    )
