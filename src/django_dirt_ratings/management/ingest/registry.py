"""The step registry: one declarative :class:`StepSpec` per derivative type.

This is the single home the interface, de-hard-coding, and performance work all
converge on:

- **discovery** (which files, and their associated files) is a ``discover``
  callable per spec — the only place BIDS-concept queries and associations live,
  replacing the string-surgery in the old ``add_*`` commands;
- **configuration** (cuts, display modes, the template/space a step assumes)
  are fields on the spec, so a step is defined in one object instead of being
  split across a command's filter and ``_render``'s module globals;
- **rendering** is deferred to the worker via a lightweight :class:`RenderJob`
  that carries *resolved references* (URIs), never loaded volumes — so a job can
  cross the ``ProcessPoolExecutor`` boundary.

Adding a new derivative type is a new ``specs/<name>.py`` that builds a
``StepSpec`` and calls :func:`register` — no new management command.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from django_dirt_ratings import models


class BidsFile(Protocol):
    """The subset of a bidslake ``BidsFile`` the specs rely on (duck-typed so
    this module imports no neuro/bidslake code)."""

    entities: dict[str, Any]
    metadata: dict[str, Any]
    file_path: str
    uri: str

    @property
    def path(self) -> Any: ...  # UPath — local or remote

    @property
    def local_path(self) -> Path: ...  # raises for remote URIs

    def get_associated(self, kind: str | None = None) -> list[BidsFile]: ...


class Lake(Protocol):
    """The subset of a bidslake ``BidsLake`` the specs rely on."""

    def get(self, **filters: Any) -> Any: ...  # iterable of BidsFile


@dataclasses.dataclass(frozen=True, slots=True)
class RenderJob:
    """One renderable unit, discovered in the parent and rendered in a worker.

    ``inputs`` maps a role (``"mask"``, ``"anat"``, ``"v1"`` …) to a resolved
    location string (a ``file://`` path or, later, an ``s3://`` URI). The worker
    loads these once, runs the volume-wide prep once, and emits every
    ``(display, cut)`` blob — so nothing heavy is bound here and the job pickles
    cleanly across the process boundary.

    ``file1``/``file2`` are the identity stored on the resulting ``Image`` rows.
    ``cuts`` of ``(None,)`` with a single display models a one-image-per-file
    step (DTI-fit).
    """

    file1: str
    file2: str | None
    render_key: str
    inputs: dict[str, str]
    cuts: Sequence[int | None]
    displays: Sequence[models.DisplayMode]
    # Catalog-derived values attached at discovery: rational-subgroup entities
    # (e.g. ``{"space": "MNI152..."}``) and any ``catalog`` measures. Merged with the
    # computed extractors into the resulting Image's ``raw_metrics``.
    metrics: Mapping[str, float | str | None] | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class StepSpec:
    """Everything needed to discover and render one processing step's images."""

    step: models.Step
    name: str  # CLI token, e.g. "masks"
    # discover(lake, filters) -> jobs. Pure catalog queries + associations +
    # glob; no nibabel, no database. Returns [] to skip.
    discover: Callable[[Lake, Mapping[str, Any]], list[RenderJob]]


STEP_SPECS: dict[str, StepSpec] = {}


def register(spec: StepSpec) -> StepSpec:
    """Register a spec under its CLI ``name`` (idempotent per name)."""
    STEP_SPECS[spec.name] = spec
    return spec
