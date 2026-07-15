import typing

import celery

from django_dirt_ratings import models, selectors


@celery.shared_task
def run_db_query_async(step: int, last_pk: int | None = None) -> dict[str, typing.Any]:
    """Find the next image to rate; return a JSON-safe reference to it.

    Dispatched as a background task so the (potentially slow) fewest-ratings
    query for the *next* image runs while the reviewer annotates the current
    one — the prefetch that keeps image-to-image transitions instant.
    """
    image = selectors.image_with_fewest_ratings(step=models.Step(step), exclude=last_pk)
    return {"id": image.pk, "step": image.step}
