"""Open a bidslake DuckDB catalog for querying.

Indexing a dataset into a catalog is done by the ``bidslake index`` CLI (the Rust
indexer); this module only opens the resulting ``.duckdb`` file. ``base_dir``
rebases every dataset's stored root, for querying a dataset that has moved since
it was indexed (e.g. a cluster path bound at a different mount in a container).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def open_lake(
    catalog: str | Path, *, base_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Open the bidslake catalog at ``catalog`` (read-only)."""
    import bidslake

    return bidslake.open(str(catalog), base_dir=base_dir)
