"""Open a bidslake DuckDB catalog for querying, and run unit queries over it.

Indexing a dataset into a catalog is done by the ``bidslake index`` CLI (the Rust
indexer); this module only opens the resulting ``.duckdb`` file. ``base_dir``
rebases every dataset's stored root, for querying a dataset that has moved since
it was indexed (e.g. a cluster path bound at a different mount in a container).

This module is also the specs' seam to bidslake's *unit* machinery
(``sibling``/``unresolved``/``lake.sql``): :func:`unit_rows` resolves every
associated file for a whole step in **one** catalog query, where a per-candidate
single-file lookup costs a ~50 ms round-trip each — thousands of them for a
large study. The specs stay bidslake-import-free (see ``registry.Lake``);
everything bidslake-typed lives behind the functions here.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import typing
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def open_lake(
    catalog: str | Path, *, base_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Open the bidslake catalog at ``catalog`` (read-only)."""
    # bidslake exists only in the manage env (Python 3.14 + cargo build); the dev
    # env that type-checks this package never has it, hence the suppression.
    import bidslake  # ty: ignore[unresolved-import]

    return bidslake.open(str(catalog), base_dir=base_dir)


@dataclasses.dataclass(frozen=True, slots=True)
class Role:
    """One sibling to resolve per anchor row of a unit query.

    ``join`` names the columns the sibling must share with the anchor (matched
    NULL-safely, so sessionless files still pair). ``where`` filters the sibling
    by column equality, with ``None`` meaning ``IS NULL``. ``basename`` instead
    matches by path suffix, for volumes whose identity is a fixed filename
    (FreeSurfer's ``brain.mgz``) rather than any concept column.

    An ``optional`` role that resolves to nothing leaves the job standing instead
    of skipping it, so a spec can offer an input only some datasets have (an
    ``aseg`` segmentation, say). The extractors needing it simply do not run (see
    ``MetricExtractor.requires``), while everything else is measured as usual.
    """

    join: tuple[str, ...]
    where: Mapping[str, Any] | None = None
    basename: str | None = None
    optional: bool = False


class Resolved(typing.NamedTuple):
    """A resolved role: where it is, and which indexed tree it came from.

    ``root_uri`` is what pairs a file with the dataset-root sidecars that describe
    it (a ``_dseg.tsv`` label lookup, say) — those carry no entities to join on,
    and a study indexed as many roots cannot pair them by dataset either.
    """

    local: str
    file_path: str
    root_uri: str


@dataclasses.dataclass(frozen=True, slots=True)
class UnitRow:
    """One anchor file with its resolved roles, from :func:`unit_rows`."""

    file_path: str
    local: str
    entities: dict[str, Any]
    roles: dict[str, Resolved | None]
    #: role -> match count for every role that is not exactly one file
    #: (0 = missing, 2+ = ambiguous). Either way the role stays None, never
    #: resolved by silently picking a candidate.
    unresolved: dict[str, int]
    #: roles the spec marked optional: unresolved, they leave the job standing.
    optional_roles: frozenset[str] = dataclasses.field(default_factory=frozenset)

    def warn_unresolved(self, logger: logging.Logger) -> bool:
        """Log each unresolved role; True when this row must be skipped.

        Missing (0 matches) logs at DEBUG — an anchor with nothing to pair is
        routine (masks exist in spaces that have no T1w). Ambiguous (2+) is a
        WARNING: the query under-specifies, and picking one is never safe. Only a
        *required* role forces the skip; an optional one is simply absent.
        """
        for role, n in self.unresolved.items():
            fate = "leaving" if role in self.optional_roles else "skipping"
            if n == 0:
                logger.debug("%s %s: %s matched nothing", fate, self.file_path, role)
            else:
                logger.warning(
                    "%s %s: %s was ambiguous (%d matches)",
                    fate,
                    self.file_path,
                    role,
                    n,
                )
        return any(role not in self.optional_roles for role in self.unresolved)


def unit_rows(
    lake: Any,
    *,
    anchor: Mapping[str, Any],
    entities: Sequence[str] = (),
    roles: Mapping[str, Role] | None = None,
    anchor_basename: str | None = None,
    require: Sequence[str] = (),
) -> list[UnitRow]:
    """Each file matching ``anchor``, with every role resolved — one query.

    ``anchor`` filters columns by equality (``None`` = ``IS NULL``);
    ``anchor_basename`` additionally pins the anchor's path suffix, and
    ``require`` names columns that must be non-NULL (e.g. ``("sub",)`` to keep
    FreeSurfer's subject-less ``fsaverage`` tree out). ``entities`` are anchor
    columns copied onto each :class:`UnitRow`.
    """
    # bidslake/sqlalchemy exist only in the manage env; see open_lake.
    import bidslake  # ty: ignore[unresolved-import]
    from bidslake.schema.models import AllFiles  # ty: ignore[unresolved-import]
    from sqlalchemy import select, true

    roles = dict(roles or {})
    a = AllFiles.__table__.alias("a")
    conds = [a.c[k].is_(None) if v is None else a.c[k] == v for k, v in anchor.items()]
    if anchor_basename is not None:
        # `autoescape` is not optional: BIDS names are mostly `_`, a LIKE wildcard.
        conds.append(a.c.file_path.endswith(f"/{anchor_basename}", autoescape=True))
    conds += [a.c[k].is_not(None) for k in require]

    cols = [a.c.dataset_id, a.c.root_uri, a.c.file_path]
    cols += [a.c[k] for k in entities]
    frm = a
    for name, role in roles.items():
        lat, sel = (
            _basename_sibling(a, name, role)
            if role.basename is not None
            else bidslake.sibling(a, name, role.join, role.where)
        )
        cols += sel
        frm = frm.outerjoin(lat, true())

    stmt = select(*cols).select_from(frm).where(*conds)
    out: list[UnitRow] = []
    for row in lake.sql(stmt).iter_rows(named=True):
        resolved: dict[str, Resolved | None] = {}
        for name in roles:
            if row[f"{name}__n"] == 1:
                local = bidslake.to_local_path(bidslake.sibling_path(lake, row, name))
                resolved[name] = Resolved(
                    str(local), row[f"{name}__file_path"], row[f"{name}__root_uri"]
                )
            else:
                resolved[name] = None
        out.append(
            UnitRow(
                file_path=row["file_path"],
                local=str(bidslake.to_local_path(bidslake.sibling_path(lake, row))),
                entities={k: row[k] for k in entities},
                roles=resolved,
                unresolved=bidslake.unresolved(row, roles),
                optional_roles=frozenset(n for n, r in roles.items() if r.optional),
            )
        )
    return out


def _basename_sibling(anchor: Any, name: str, role: Role) -> tuple[Any, list[Any]]:
    """``bidslake.sibling``, but matching the sibling by path suffix.

    Mirrors the lateral ``sibling`` builds (same ``<name>__*`` columns, same
    one-row aggregation) with a ``file_path`` suffix condition that its
    equality-only ``where`` cannot express.
    """
    from sqlalchemy import and_, func, select

    f = getattr(anchor, "element", anchor).alias(f"f_{name}")
    conds = [f.c.file_path.endswith(f"/{role.basename}", autoescape=True)]
    conds += [
        f.c[k].is_(None) if v is None else f.c[k] == v
        for k, v in (role.where or {}).items()
    ]
    conds += [f.c[k].is_not_distinct_from(anchor.c[k]) for k in role.join]
    lat = (
        select(
            func.list(f.c.dataset_id).label("d"),
            func.list(f.c.root_uri).label("r"),
            func.list(f.c.file_path).label("p"),
        )
        .select_from(f)
        .where(and_(*conds))
        .lateral(name)
    )
    return lat, [
        func.list_extract(lat.c.d, 1).label(f"{name}__dataset_id"),
        func.list_extract(lat.c.r, 1).label(f"{name}__root_uri"),
        func.list_extract(lat.c.p, 1).label(f"{name}__file_path"),
        func.coalesce(func.len(lat.c.p), 0).label(f"{name}__n"),
    ]
