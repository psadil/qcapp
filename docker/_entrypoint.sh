#!/bin/bash

set -e

# pixi run runserver

memcached -vd -s /tmp/memcached.sock

rabbitmq-server -detached

celery -A dirt worker --detach

manage collectstatic --no-input

# manage runserver --noreload 0.0.0.0:8000
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
