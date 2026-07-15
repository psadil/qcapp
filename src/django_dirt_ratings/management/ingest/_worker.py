"""Render-pool worker bootstrap.

Kept free of any Django-model import on purpose: a spawned ``ProcessPoolExecutor``
worker unpickles this initializer during bootstrap, *before* ``django.setup()``
has run, so importing models here would raise ``AppRegistryNotReady``. The
initializer runs first and configures Django; only then does the worker unpickle
and import the render function (which does import models).
"""

from __future__ import annotations


def init_django() -> None:
    import django

    django.setup()
