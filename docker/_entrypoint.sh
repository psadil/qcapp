#!/bin/bash

set -e

# pixi run runserver

memcached -vd -s /tmp/memcached.sock

rabbitmq-server -detached

celery -A qcapp worker --detach

# manage runserver --noreload 0.0.0.0:8000
granian \
	qcapp.asgi:application \
	--interface asginl \
	--host 0.0.0.0 \
	--workers 2 \
	--runtime-mode st \
	--loop uvloop \
	--no-ws
