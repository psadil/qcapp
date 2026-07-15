"""Shared ingest loop for the add_* management commands.

This lives in the management layer because the render callables it drives
import the heavy neuroimaging stack (available only in the ``manage``
environment); all database work is delegated to the light services/selectors
layer, which the web runtime also uses.
"""

import logging
import typing

from django_dirt_ratings import models, selectors, services


def ingest_series(
    *,
    file1: str,
    step: models.Step,
    cuts: typing.Iterable[int],
    render: typing.Callable[..., bytes],
    file2: str | None = None,
    update: bool = False,
) -> None:
    """Render and store one Image per (display mode, cut).

    Existing images are skipped unless ``update`` is set, in which case their
    bytes are refreshed in place (preserving any ratings already collected).
    Rendering only happens when a write will follow.
    """
    for display_mode in models.DisplayMode:
        logging.info(f"{display_mode=}")
        for cut in cuts:
            logging.info(f"{cut=}")
            exists = selectors.image_exists(
                slice=cut, file1=file1, display=display_mode, step=step
            )
            if exists and not update:
                logging.info("Found object. Skipping")
                continue

            img = render(cut=cut, display_mode=display_mode)
            services.image_upsert(
                img=img,
                slice=cut,
                file1=file1,
                file2=file2,
                display=display_mode,
                step=step,
            )
