"""Apply (validate → persist → activate) a review plan, or show the active one.

The web app reads the *active* plan from the database; this command is how a
``dirt.toml`` gets there. Web-safe (no neuro stack): validates the plan and stores
it verbatim as the sole active :class:`~django_dirt_ratings.models.ReviewPlan`.

    manage plan dirt.toml     # validate + persist + activate
    manage plan --show        # print the active plan's TOML
"""

import typing as t
from pathlib import Path

import typer
from django.conf import settings
from django_typer.completers import path
from django_typer.management import TyperCommand

from django_dirt_ratings import plan as plan_mod
from django_dirt_ratings import services


class Command(TyperCommand):
    def handle(
        self,
        file: t.Annotated[
            Path | None,
            typer.Argument(
                exists=True,
                file_okay=True,
                dir_okay=False,
                readable=True,
                shell_complete=path.paths,
                help="A dirt.toml review plan (defaults to $DIRT_PLAN).",
            ),
        ] = None,
        show: t.Annotated[
            bool,
            typer.Option(help="Print the active plan's TOML and exit."),
        ] = False,
    ) -> None:
        """Apply a review plan (default) or show the active one (--show)."""
        if show:
            record = plan_mod.active_record()
            self.stdout.write(record.toml if record else "No active review plan.")
            return

        if file is None:
            if not settings.DIRT_PLAN:
                raise typer.BadParameter("provide a plan file or set DIRT_PLAN")
            file = Path(settings.DIRT_PLAN)

        text = file.read_text()
        try:
            parsed = plan_mod.parse(text)  # strict validation
        except plan_mod.PlanError as e:
            raise typer.BadParameter(str(e)) from e

        services.plan_apply(name=parsed.name, text=text)
        self.stdout.write(
            self.style.SUCCESS(
                f"Applied plan {parsed.name or '(unnamed)'!r}: "
                f"strategy={parsed.strategy.value}, "
                f"{len(parsed.steps)} step(s) [{', '.join(s.step.cli_name for s in parsed.steps)}]."
            )
        )
