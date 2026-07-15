#!/bin/bash

set -e

manage collectstatic --no-input

# The SQLite databases live under $DB's directory (see settings.py); it must be
# a mounted volume for data to survive the container.
mkdir -p "$(dirname "${DB:-/app/db/dirt.db}")"
manage migrate --no-input
manage createcachetable --database cache

granian \
	dirt.asgi:application \
	--interface asginl \
	--host 0.0.0.0 \
	--workers 2 \
	--runtime-mode st \
	--loop uvloop \
	--static-path-route /static \
	--static-path-mount /app/static \
	--no-ws
