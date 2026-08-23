"""Render-pool worker bootstrap.

Kept free of any Django-model import on purpose: a spawned ``ProcessPoolExecutor``
worker unpickles this initializer during bootstrap, *before* ``django.setup()``
has run, so importing models here would raise ``AppRegistryNotReady``. The
initializer runs first and configures Django; only then does the worker unpickle
and import the render function (which does import models).
"""

from __future__ import annotations


def init_django() -> None:
    import os

    # One render worker per core already: keep BLAS/OpenMP pools (and any
    # display backend probing) from oversubscribing, before the heavy imports.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("MPLBACKEND", "Agg")

    import django

    django.setup()
