#!/bin/bash
# Run the bidslake indexer CLI from the sibling checkout at ../bidslake — but
# only when that checkout sits at the rev pyproject.toml pins for the python
# reader. Catalogs written by a drifted CLI may be unreadable by the pinned
# reader (bidslake catalog formats change without migration), so drift fails
# loudly here instead of at query time. Set BIDSLAKE_UNPINNED=1 to bypass the
# check while iterating on bidslake itself — the reason the CLI runs from a
# checkout (fast incremental builds) rather than from the pinned git rev.
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel)
BIDSLAKE_DIR="${PROJECT_ROOT}/../bidslake"

# The same extraction (and empty-result guard) the Dockerfile uses, so the pin
# has one spelling everywhere.
PINNED="$(grep -oE 'bidslake\.git@[0-9a-f]+' "${PROJECT_ROOT}/pyproject.toml" | head -1 | cut -d@ -f2)"
[ -n "$PINNED" ] || {
	echo 'ERROR: no bidslake rev found in pyproject.toml' >&2
	exit 1
}

CHECKOUT="$(git -C "$BIDSLAKE_DIR" rev-parse HEAD)"
if [ "$CHECKOUT" != "$PINNED" ]; then
	if [ "${BIDSLAKE_UNPINNED:-0}" = "1" ]; then
		echo "WARNING: ../bidslake is at ${CHECKOUT:0:12}, not the pinned ${PINNED:0:12}; proceeding (BIDSLAKE_UNPINNED=1)" >&2
	else
		{
			echo "ERROR: ../bidslake is at ${CHECKOUT:0:12} but pyproject.toml pins ${PINNED:0:12}."
			echo "A CLI built from a drifted rev can write catalogs the pinned reader cannot open."
			echo "Fix:    git -C '${BIDSLAKE_DIR}' checkout ${PINNED}"
			echo "Bypass: BIDSLAKE_UNPINNED=1 (while iterating on bidslake itself)"
		} >&2
		exit 1
	fi
fi

exec cargo run --release --manifest-path "${BIDSLAKE_DIR}/Cargo.toml" --bin bidslake -- "$@"
