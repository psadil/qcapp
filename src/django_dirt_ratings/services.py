"""
Services module — business logic for the django_dirt_ratings app.

Following the Django Styleguide, services are functions that take care of
writing things to the database. Business logic that was previously embedded
in model methods or views is consolidated here.
"""

import json
import logging

from django import http, shortcuts

from django_dirt_ratings import models


def _get_image_and_session_from_request(
    request: http.HttpRequest,
) -> tuple[models.Image, models.Session]:
    """Look up the current Image and Session from the request session."""
    image = shortcuts.get_object_or_404(
        models.Image, pk=request.session.get("image_id")
    )
    session = shortcuts.get_object_or_404(
        models.Session, pk=request.session.get("session_id")
    )
    return image, session


def rating_create(*, instance: models.Rating, request: http.HttpRequest) -> None:
    """
    Populate a Rating instance with request-derived fields and save it.

    The instance is expected to come from a form (``form.save(commit=False)``),
    with user-submitted fields already set. This service adds the image and
    session references obtained from the request session.
    """
    image, session = _get_image_and_session_from_request(request)
    instance.image = image
    instance.session = session

    logging.info("saving rating via service")
    instance.full_clean()
    instance.save()


def clicked_coordinate_create(
    *, instance: models.ClickedCoordinate, request: http.HttpRequest
) -> None:
    """
    Populate a ClickedCoordinate from form + request data and save.

    Handles the special case where the POST contains a ``points`` JSON
    payload: each point becomes a separate ClickedCoordinate row via
    ``bulk_create``.
    """
    image, session = _get_image_and_session_from_request(request)
    instance.image = image
    instance.session = session

    points_raw = request.POST.get("points")
    points: list[dict] = [] if points_raw is None else json.loads(points_raw)

    if len(points) == 0:
        instance.save()
    else:
        # Collect all concrete, non-auto fields to replicate across points
        common_fields: dict = {}
        for field in instance._meta.get_fields():
            if (
                field.concrete
                and not field.auto_created
                and field.name not in ("id", "pk")
            ):
                common_fields[field.name] = getattr(instance, field.name)

        objs = [
            models.ClickedCoordinate(**{**common_fields, **point}) for point in points
        ]
        models.ClickedCoordinate.objects.bulk_create(objs)
