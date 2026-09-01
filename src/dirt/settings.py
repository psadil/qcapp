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

# Optional default path to a review plan (dirt.toml) for `manage plan`. The web app
# reads the *active* plan from the database, not this file; this is only a
# convenience default so `manage plan` (and a Docker entrypoint) can apply it.
DIRT_PLAN = env.str("DIRT_PLAN", default=None)

# Base URL of the documentation site; templates link raters to its tutorials
# (e.g. the spatial-normalization rating walkthrough). Self-hosted deployments
# that mirror the docs can point this elsewhere.
DIRT_DOCS_URL = env.str("DIRT_DOCS_URL", default="https://psadil.github.io/dirt")


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
    "axes",
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
    # must be last: it wraps authentication to observe the outcome
    "axes.middleware.AxesMiddleware",
]

# Login throttling (django-axes). AxesStandaloneBackend goes first and
# short-circuits a locked-out attempt before ModelBackend hashes a password.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # hours
AXES_RESET_ON_SUCCESS = True
# Lock the (address, username) *pair*, not either alone: username alone lets
# anyone freeze a known rater out; address alone, behind one shared proxy,
# would freeze out everybody at once.
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]

# Raters are issued a password by `manage create_rater` and never set their
# own, so only login/logout are routed (see dirt/urls.py).
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "login"

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
                "django_dirt_ratings.context_processors.docs",
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

# Rendered QC images are ordinary Django media: written through
# `default_storage` (see django_dirt_ratings/storage.py for their layout) and
# served from MEDIA_ROOT by the media view in dirt/urls.py.
# Relative on purpose: Django prepends the script prefix per request, so the
# same setting serves /media/... at the root and /dirt/media/... under one.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR.parent / "media")))

# Image-ingest API (django_dirt_ratings/api.py). Follows DEBUG, and for the
# same reason it exists: a source checkout gets the endpoint for free, while a
# bare deployment does not expose a write API onto the image store — the
# deploy config opts in. With it off, the API 401s whatever credentials arrive.
INGEST_ENABLED = env.bool("DIRT_INGEST_ENABLED", default=DEBUG)

# The API's own ceilings. A pushed unit arrives as two multipart FILE parts,
# and DATA_UPLOAD_MAX_MEMORY_SIZE is calculated excluding file upload data, so
# its 2.5 MB default keeps guarding the login and rating POSTs untouched. A
# unit is 9-15 images at ~55 KB each, but animated coregistration/dtifit AVIFs
# run far larger — hence the generous per-image ceiling.
INGEST_MAX_TAR_BYTES = env.int("DIRT_INGEST_MAX_TAR_BYTES", default=64 * 1024 * 1024)
INGEST_MAX_IMAGE_BYTES = env.int("DIRT_INGEST_MAX_IMAGE_BYTES", default=8 * 1024 * 1024)
INGEST_MAX_IMAGES = env.int("DIRT_INGEST_MAX_IMAGES", default=64)

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

# Django defaults this to "same-origin", which browsers then log a warning about
# on insecure origins (reviewing over http on a LAN IP, say) where the header is
# ignored anyway. Drop it in dev for a clean console; deployments (https) below
# restore it.
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

if DEPLOYED:
    SESSION_COOKIE_SECURE = True
    SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
    # https://rtl.chrisadams.me.uk/2024/05/til-keeping-your-hair-when-upgrading-django-3-2-behind-a-caddy-server/
    # also needed because this is behind traefik
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
    # REMOTE_ADDR is the proxy's container address, so the client IP has to
    # come from X-Forwarded-For — but only in a way a client cannot forge. The
    # proxy appends the peer it heard from (never itself), so a request that
    # arrives with no XFF reaches Django with exactly one entry: hence a proxy
    # count of 0, not 1 — a forged client XFF then falls back to the proxy's
    # IP instead of being trusted.
    AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
    AXES_IPWARE_PROXY_COUNT = 0
