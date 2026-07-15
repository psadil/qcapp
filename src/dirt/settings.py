"""
Django settings for the dirt project.

Configuration is environment-driven (django-environ): every deployment knob
is an env var with a development-friendly default. The database and the cache
both run on SQLite, following
https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production
"""

from pathlib import Path

import environ

env = environ.Env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = env.str("DJANGO_SECRET_KEY")

DEBUG = env.bool("DJANGO_DEBUG", default=False)

DEPLOYED = env.bool("DJANGO_DEPLOYED", default=False)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "[::1]", "0.0.0.0"],
)


# Application definition

INSTALLED_APPS = [
    "django_dirt_ratings",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_typer",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dirt.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "dirt.wsgi.application"
ASGI_APPLICATION = "dirt.asgi.application"

# Database & cache — SQLite in production
# https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production
# The cache lives in its own database so ephemeral data stays out of backups
# of the main database (create its table with:
# manage createcachetable --database cache).

DB_PATH = Path(env.str("DB", default=str(BASE_DIR.parent / "db" / "dirt.db")))
CACHE_DB_PATH = Path(env.str("CACHE_DB", default=str(DB_PATH.parent / "cache.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _sqlite_options() -> dict:
    """Production-grade SQLite connection options (Django 5.1+)."""
    return {
        "transaction_mode": "IMMEDIATE",
        "timeout": 5,  # seconds
        "init_command": """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA mmap_size=134217728;
            PRAGMA journal_size_limit=27103364;
            PRAGMA cache_size=2000;
        """,
    }


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DB_PATH,
        "OPTIONS": _sqlite_options(),
    },
    "cache": {
        # A separate SQLite file so ephemeral cache data stays out of backups
        # of the main database (see the DatabaseCache note above).
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": CACHE_DB_PATH,
        "OPTIONS": _sqlite_options(),
    },
}

DATABASE_ROUTERS = ["dirt.routers.CacheRouter"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache",
    }
}


# Password validation
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/New_York"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/stable/howto/static-files/
# Absolute so it resolves correctly on sub-path pages (e.g. /mask/), not just
# the site root; also matches granian's --static-path-route in the container.
STATIC_URL = "/static/"

# granian: must be mounted with --static-path-mount
STATIC_ROOT = BASE_DIR.parent / "static"

# Default primary key field type
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# https://docs.djangoproject.com/en/stable/topics/logging/
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamp": {"format": "%(asctime)s | %(levelname)-8s | %(message)s"}
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "timestamp"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

if DEPLOYED:
    SESSION_COOKIE_SECURE = True
    SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
    # https://rtl.chrisadams.me.uk/2024/05/til-keeping-your-hair-when-upgrading-django-3-2-behind-a-caddy-server/
    # also needed because this is behind traefik
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
