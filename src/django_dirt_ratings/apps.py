import mimetypes

from django.apps import AppConfig


class RatingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_dirt_ratings"
    label = "django_dirt_ratings"

    def ready(self) -> None:
        # Some platforms' mimetypes tables predate AVIF; media serving needs it.
        mimetypes.add_type("image/avif", ".avif")
