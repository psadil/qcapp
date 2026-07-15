"""Database routers for the dirt project."""

DJANGO_CACHE_APP_LABEL = "django_cache"


class CacheRouter:
    """Route Django's database-cache table to the dedicated "cache" database."""

    def db_for_read(self, model, **hints):
        if model._meta.app_label == DJANGO_CACHE_APP_LABEL:
            return "cache"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == DJANGO_CACHE_APP_LABEL:
            return "cache"
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == DJANGO_CACHE_APP_LABEL:
            return db == "cache"
        # Everything else lives only in "default"; without this, migrating
        # the cache alias would try to create the GIS models on the plain
        # sqlite3 backend.
        return db == "default"
