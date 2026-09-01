# syntax=docker/dockerfile:1-labs
#
# One ENVIRONMENT-parameterized image for the web app (default) and the
# manage/ingest CLI (manage). The build target is selected from ENVIRONMENT via
# `FROM ...-${ENVIRONMENT}`, so the web build never runs the cargo/bidslake step
# (BuildKit prunes unused stages). Requires BuildKit (implied by the 1-labs
# syntax above; on by default in modern Docker).
#
#   web (default):  docker buildx build --platform=linux/amd64 --provenance=true -t psadil/dirt .
#   manage:         docker buildx build --platform=linux/amd64 --provenance=true \
#                     --build-arg ENVIRONMENT=manage -t psadil/dirt:manage .

# The pixi-docker image tag is <version>-<distro>; -noble pins glibc parity with
# the ubuntu:24.04 runtime. (Docker images lag the pixi CLI release slightly, so
# this is the latest published tag, not necessarily the newest pixi.)
ARG PIXI_VERSION=0.77.0
ARG BASE_IMAGE=ubuntu:24.04
ARG ENVIRONMENT=default

# --------------------------------------------------------------------------
# Shared builder — the official pixi image (pixi preinstalled, multi-arch).
# Keep it on the same Ubuntu release (noble/24.04) as BASE_IMAGE so the
# cargo-built bidslake binary's system glibc matches the runtime.
#   git:             pixi builds git-sourced pypi deps (bidslake).
# Deliberately no build-essential: the manage env ships conda's gcc/gxx, and a
# system compiler on PATH lets cc-rs build duckdb's bundled C++ against Ubuntu's
# glibc while conda's linker resolves against its older sysroot — undefined
# __isoc23_* symbols, legal in the bidslake-py cdylib, fatal linking the CLI.
# Air-gapped / ghcr-blocked fallback: replace the FROM with `FROM ubuntu:24.04`
# and prepend:
#   RUN curl -Ls "https://github.com/prefix-dev/pixi/releases/download/v${PIXI_VERSION}/pixi-$(uname -m)-unknown-linux-musl" -o /usr/local/bin/pixi && chmod +x /usr/local/bin/pixi
# --------------------------------------------------------------------------
FROM ghcr.io/prefix-dev/pixi:${PIXI_VERSION}-noble AS builder-base
ARG ENVIRONMENT
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# The single "dirt" distribution ships BOTH top-level packages (dirt AND
# django_dirt_ratings; see src/dirt.egg-info/top_level.txt). The editable install
# only puts /app/src on sys.path, so both package dirs must physically exist —
# and django_dirt_ratings is INSTALLED_APPS[0], so omitting it breaks every
# `manage` command at django.setup(). Copy both.
COPY --parents ./pixi.lock ./pyproject.toml ./src/dirt ./src/django_dirt_ratings /app/
RUN pixi install --locked -e ${ENVIRONMENT}

# ---- web (default) builder: nothing extra ----
FROM builder-base AS builder-default

# ---- manage builder: also ship the bidslake indexer CLI into the env's bin.
# `pixi install` above provides only the bidslake *reader* — the maturin-built
# `bidslake-py` python package, which opens catalogs but cannot build them. The
# indexer is a separate crate in the same repo and ships no wheel, so it needs its
# own cargo build. Its rev is read from the dep pyproject.toml already pins rather
# than repeated here, so the CLI and the reader cannot drift apart. Run cargo via
# `pixi run` so it uses the env's own rust toolchain (a bare cargo could pick up a
# mismatched rustc from PATH). ----
FROM builder-base AS builder-manage
ARG ENVIRONMENT
RUN set -eu; \
    REV="$(grep -oE 'bidslake\.git@[0-9a-f]+' pyproject.toml | head -1 | cut -d@ -f2)"; \
    # grep's exit status is hidden by the pipe, so check the result, or a pyproject
    # reformat would silently build `--rev ""` (i.e. the default branch).
    [ -n "$REV" ] || { echo 'ERROR: no bidslake rev found in pyproject.toml' >&2; exit 1; }; \
    echo "Building bidslake indexer CLI at rev $REV"; \
    pixi run -e ${ENVIRONMENT} cargo install \
    --git https://github.com/psadil/bidslake.git --rev "$REV" \
    --locked --bin bidslake --root /app/.pixi/envs/${ENVIRONMENT} bidslake

# ---- select the builder by ENVIRONMENT (ARG-in-FROM; needs BuildKit) ----
FROM builder-${ENVIRONMENT} AS builder

# --------------------------------------------------------------------------
# Shared runtime.
# --------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS runtime-base

ARG ENVIRONMENT
ARG MAMBA_USER=mambauser
ARG MAMBA_USER_ID=57439
ARG MAMBA_USER_GID=57439
ENV MAMBA_USER=$MAMBA_USER
ENV MAMBA_USER_ID=$MAMBA_USER_ID
ENV MAMBA_USER_GID=$MAMBA_USER_GID

COPY --chmod=0544 docker/_dockerfile_initialize_user_accounts.sh /usr/local/bin/_dockerfile_initialize_user_accounts.sh
RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh

USER $MAMBA_USER

WORKDIR /app
COPY --from=builder --chown=$MAMBA_USER:$MAMBA_USER /app /app

ENV TZ=America/Chicago
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# Complete activation: the activate.d scripts present (rust, and manage's compilers)
# export build-time vars only, so PATH + CONDA_PREFIX suffice. Must match the builder path.
ENV PATH=/app/.pixi/envs/${ENVIRONMENT}/bin:$PATH
ENV CONDA_PREFIX=/app/.pixi/envs/${ENVIRONMENT}

# ---- web (default) runtime: granian, via the mount-check/migrate entrypoint ----
FROM runtime-base AS runtime-default
COPY --chmod=0544 --chown=$MAMBA_USER:$MAMBA_USER docker/_entrypoint.sh /usr/local/bin/_entrypoint
# Static assets bake into the image (granian serves them from /app/static), and
# `check` catches a broken settings module at build rather than first boot. The
# throwaway secret only satisfies settings import. Settings mkdir the db path at
# import, so remove it again and pre-create both mount points empty.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret manage collectstatic --no-input \
    && DJANGO_SECRET_KEY=build-only-not-a-secret manage check \
    && rm -rf /app/db \
    && install -d /app/db /app/media
EXPOSE 8000
ENTRYPOINT [ "/usr/local/bin/_entrypoint" ]
CMD ["granian", "dirt.asgi:application", \
    "--interface", "asginl", \
    "--host", "0.0.0.0", "--port", "8000", \
    "--workers", "2", "--runtime-mode", "st", "--loop", "uvloop", \
    "--static-path-route", "/static", \
    "--static-path-mount", "/app/static", \
    "--static-path-expires", "300", \
    "--no-ws"]

# ---- manage runtime: the management CLI (render / recount / bidslake …) ----
FROM runtime-base AS runtime-manage
ENTRYPOINT [ "manage" ]
CMD ["--help"]

# ---- select the runtime by ENVIRONMENT; last stage is the default build target ----
FROM runtime-${ENVIRONMENT} AS final
