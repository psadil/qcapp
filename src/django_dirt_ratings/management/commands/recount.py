"""Recompute ``Image.n_reviews`` from the actual submission counts.

The counter is maintained incrementally by the services layer, so it only drifts
if a Rating/Annotation is ever deleted out of band (e.g. via the admin). This
command is the safety valve: it recounts distinct submissions per image and
writes back any that disagree. Web-safe (no neuro stack).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, F

from django_dirt_ratings import models


class Command(BaseCommand):
    help = "Recompute Image.n_reviews from actual Rating/Annotation counts."

    def handle(self, *args, **options) -> None:
        updated = 0
        for step in models.Step:
            # Compare counter to count in SQL and fetch only the disagreeing
            # (pk, actual) pairs — never the image blobs.
            stale_counts = (
                models.Image.objects.filter(step=step.value)
                .annotate(_actual=Count(step.related_name, distinct=True))
                .exclude(n_reviews=F("_actual"))
                .values_list("pk", "_actual")
            )
            stale = [
                models.Image(id=image_id, n_reviews=actual)
                for image_id, actual in stale_counts
            ]
            if stale:
                models.Image.objects.bulk_update(stale, ["n_reviews"])
                updated += len(stale)
        self.stdout.write(
            self.style.SUCCESS(f"Recounted n_reviews; updated {updated} image(s).")
        )
