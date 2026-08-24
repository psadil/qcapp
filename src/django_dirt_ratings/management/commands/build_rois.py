"""Pre-build the spatial-normalization ROI cache for one or more spaces.

Building fetches TemplateFlow assets (network) and, for non-canonical spaces,
runs a few minutes of registration — run this on a networked login node before
offline cluster renders. Rendering then finds the artifacts in the cache
(``DIRT_ROI_CACHE``, default ``~/.cache/dirt/rois``) and never touches the
network.
"""

import typing as t
from pathlib import Path

import typer
from django_typer.management import TyperCommand

from django_dirt_ratings.management.ingest import rois


class Command(TyperCommand):
    def handle(
        self,
        space: t.Annotated[
            list[str],
            typer.Argument(
                help="Template space(s) to build, e.g. MNI152NLin2009cAsym. "
                f"Recipes exist for: {', '.join(sorted(rois._RECIPES))}.",
            ),
        ],
        cohort: t.Annotated[
            str | None,
            typer.Option(help="Template cohort entity, for cohort-split templates."),
        ] = None,
        cache_dir: t.Annotated[
            Path | None,
            typer.Option(
                help="Cache directory (default: DIRT_ROI_CACHE or ~/.cache/dirt/rois)."
            ),
        ] = None,
    ) -> None:
        """Build (or reuse) the ROI artifact for each requested space."""
        for name in space:
            try:
                artifact = rois.ensure_rois(name, cohort, cache_dir=cache_dir)
            except rois.RoiUnavailableError as err:
                raise typer.BadParameter(str(err)) from err
            self.stdout.write(self.style.SUCCESS(f"{name}: {artifact.dseg}"))
