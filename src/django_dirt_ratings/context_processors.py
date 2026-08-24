"""Template context processors (registered in ``dirt.settings.TEMPLATES``)."""

from django.conf import settings
from django.http import HttpRequest


def docs(request: HttpRequest) -> dict[str, str]:
    """Expose the documentation site URL so templates can link rater tutorials."""
    return {"docs_url": settings.DIRT_DOCS_URL}
