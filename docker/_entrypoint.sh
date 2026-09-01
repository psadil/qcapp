#!/bin/bash

set -euo pipefail

# Both durable paths must be mount points, or their contents die with the
# container. A typo'd -v does not fail loudly: settings.py mkdirs the db path
# at import and would happily write into the container's ephemeral layer.
# Compare device numbers rather than calling mountpoint(1) — both bind mounts
# and named volumes land on a different st_dev than the overlay root.
if [ "${DIRT_ALLOW_EPHEMERAL_STATE:-0}" != "1" ]; then
	root_dev="$(stat -c %d /app)"
	for d in /app/db /app/media; do
		if [ "$(stat -c %d "$d")" = "$root_dev" ]; then
			echo "FATAL: $d is not a mounted volume; refusing to start." >&2
			echo "       Data written there dies with the container. Mount it, e.g." >&2
			echo "         -v /srv/dirt/db:/app/db -v /srv/dirt/media:/app/media" >&2
			echo "       Set DIRT_ALLOW_EPHEMERAL_STATE=1 for a throwaway smoke test." >&2
			exit 1
		fi
	done
fi

# WAL needs write permission on the DIRECTORY, not just on the database file,
# to create the -wal/-shm sidecars. A host directory left owned by root reads
# fine, so the site would look healthy right up until the first write fails;
# check now instead.
for d in /app/db /app/media; do
	if ! touch "$d/.dirt-writable" 2>/dev/null; then
		echo "FATAL: $d is not writable by uid $(id -u)." >&2
		echo "       On the host: chown -R 57439:57439 the mounted directory." >&2
		exit 1
	fi
	rm -f "$d/.dirt-writable"
done

# Idempotent start-up steps: schema, then the cache table (the DatabaseCache
# lives in its own sqlite file — see settings.py).
manage migrate --no-input
manage createcachetable --database cache

# exec the CMD rather than hardcoding granian, so the same image also runs
# one-off commands: docker compose run --rm dirt manage create_rater alice
exec "$@"
