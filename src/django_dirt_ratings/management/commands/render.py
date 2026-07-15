"""Render QC images from a bidslake catalog — the one image-generation command.

Replaces the five ``add_*`` commands: it opens a bidslake ``.duckdb`` catalog and
delegates to the ingest orchestrator, which auto-discovers which steps have files
present. Build a catalog first with ``bidslake index -i <dataset> -o study.duckdb``.
"""

import typing as t
from pathlib import Path

import typer
from django_typer.completers import path
from django_typer.management import TyperCommand

from django_dirt_ratings.management.ingest import lake as lake_mod
from django_dirt_ratings.management.ingest import orchestrator
from django_dirt_ratings.management.ingest.registry import STEP_SPECS


class Command(TyperCommand):
    def handle(
        self,
        catalog: t.Annotated[
            Path,
            typer.Argument(
                exists=True,
                file_okay=True,
                dir_okay=False,
                readable=True,
                shell_complete=path.paths,
                help="A bidslake .duckdb catalog (build one with `bidslake index`).",
            ),
        ],
        step: t.Annotated[
            list[str] | None,
            typer.Option(
                help="Step(s) to render; default is every step with files present. "
                f"Choices: {', '.join(STEP_SPECS)}.",
            ),
        ] = None,
        update: t.Annotated[
            bool,
            typer.Option(help="Re-render images already present (preserves ratings)."),
        ] = False,
        res: t.Annotated[
            str | None, typer.Option(help="Filter to a specific resolution entity.")
        ] = None,
        sub: t.Annotated[
            str | None, typer.Option(help="Filter to a specific subject label.")
        ] = None,
        workers: t.Annotated[
            int | None,
            typer.Option(help="Render worker processes (default: CPU count)."),
        ] = None,
    ) -> None:
        """Render QC images from a bidslake catalog into the database."""
        if step:
            unknown = [s for s in step if s not in STEP_SPECS]
            if unknown:
                raise typer.BadParameter(
                    f"unknown step(s): {unknown}; choose from {list(STEP_SPECS)}"
                )

        filters = {k: v for k, v in {"res": res, "sub": sub}.items() if v is not None}
        lake = lake_mod.open_lake(catalog)
        written = orchestrator.ingest_dataset(
            lake=lake,
            steps=step or None,
            filters=filters,
            update=update,
            workers=workers,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Rendered/updated {written} derivative(s).")
        )
