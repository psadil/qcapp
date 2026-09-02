"""Delete stored images that no ``Image`` row references.

The write paths delete a replaced file only after its row points away, so a
failure partway (or an out-of-band row delete, e.g. via the admin) leaves
unreachable orphans in media storage rather than broken pages. This command is
the safety valve that reclaims them. Web-safe (no neuro stack).

Those same write paths save files *before* their rows commit, so a file with
no row may simply be an ingest in flight — the default minimum age skips
anything recent rather than racing a running push or render.
"""

from __future__ import annotations

import datetime
import typing as t

import typer
from django.utils import timezone
from django_typer.management import TyperCommand

from django_dirt_ratings import models, storage


class Command(TyperCommand):
    def handle(
        self,
        dry_run: t.Annotated[
            bool, typer.Option(help="List the orphans without deleting them.")
        ] = False,
        min_age_hours: t.Annotated[
            float,
            typer.Option(
                help="Leave orphans newer than this alone (in-flight writes)."
            ),
        ] = 24.0,
    ) -> None:
        """Delete media files no Image row references."""
        referenced = set(models.Image.objects.values_list("img", flat=True))
        cutoff = timezone.now() - datetime.timedelta(hours=min_age_hours)
        orphans = [
            name
            for name in storage.stored_names()
            if name not in referenced and storage.modified_time(name) < cutoff
        ]
        for name in orphans:
            if dry_run:
                self.stdout.write(f"would delete {name}")
            else:
                storage.delete(name)
        verb = "found" if dry_run else "deleted"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(orphans)} orphan(s)."))
