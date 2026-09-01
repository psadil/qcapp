"""Recompute ``Image.priority`` from the stored metrics per the active plan.

Thin CLI over :mod:`django_dirt_ratings.prioritizing` (which the ingest API's
``POST /api/prioritize`` shares). A safety valve like ``recount``: rerun it
after ``render`` or a push brings in new measures.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from django_dirt_ratings import prioritizing


class Command(BaseCommand):
    help = "Recompute Image.priority from the stored metrics per the active plan."

    def handle(self, *args, **options) -> None:
        updated = prioritizing.run()
        self.stdout.write(
            self.style.SUCCESS(f"Recomputed priority; updated {updated} image(s).")
        )
