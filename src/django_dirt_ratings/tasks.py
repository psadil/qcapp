import typing

import celery
from asgiref import sync

from django_dirt_ratings import models, selectors


@celery.shared_task
def run_db_query_async(step: int, last_pk: int | None = None) -> dict[str, typing.Any]:
    """Find the next image to rate; return a JSON-safe reference to it."""
    image = sync.async_to_sync(selectors.image_with_fewest_ratings)(
        step=models.Step(step), exclude=last_pk
    )
    return {"id": image.pk, "step": image.step}
