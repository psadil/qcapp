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
ARG PIXI_VERSION=0.72.2
ARG BASE_IMAGE=ubuntu:24.04
ARG ENVIRONMENT=default
# bidslake indexer CLI rev; keep in sync with the pinned bidslake dep in pyproject.toml.
ARG BIDSLAKE_REV=051381e6eccad7cb253cc245e9f400b8bb1748d6

# --------------------------------------------------------------------------
# Shared builder — the official pixi image (pixi preinstalled, multi-arch).
# Keep it on the same Ubuntu release (noble/24.04) as BASE_IMAGE so the
# cargo-built bidslake binary's system glibc matches the runtime.
#   git:             pixi builds git-sourced pypi deps (bidslake).
#   build-essential: C linker for the maturin/rust build of bidslake — needed
#                    both for the manage env's `pixi install` and the cargo CLI
#                    build below (the manage env ships rust + maturin).
# Air-gapped / ghcr-blocked fallback: replace the FROM with `FROM ubuntu:24.04`
# and prepend:
#   RUN curl -Ls "https://github.com/prefix-dev/pixi/releases/download/v${PIXI_VERSION}/pixi-$(uname -m)-unknown-linux-musl" -o /usr/local/bin/pixi && chmod +x /usr/local/bin/pixi
# --------------------------------------------------------------------------
FROM ghcr.io/prefix-dev/pixi:${PIXI_VERSION}-noble AS builder-base
ARG ENVIRONMENT
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git build-essential \
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

# ---- manage builder: also ship the bidslake indexer CLI, built from the pinned
# rev into the env's bin. Run cargo via `pixi run` so it uses the env's own rust
# toolchain (a bare cargo could pick up a mismatched rustc from PATH). ----
FROM builder-base AS builder-manage
ARG ENVIRONMENT
ARG BIDSLAKE_REV
RUN pixi run -e ${ENVIRONMENT} cargo install \
    --git https://github.com/psadil/bidslake.git --rev ${BIDSLAKE_REV} \
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

# Complete activation: both envs ship zero conda activate.d scripts, so PATH +
# CONDA_PREFIX is all that is needed (no shell-hook). Must match the builder path.
ENV PATH=/app/.pixi/envs/${ENVIRONMENT}/bin:$PATH
ENV CONDA_PREFIX=/app/.pixi/envs/${ENVIRONMENT}

# ---- web (default) runtime: granian, via the migrate/collectstatic entrypoint ----
FROM runtime-base AS runtime-default
COPY --chmod=0544 --chown=$MAMBA_USER:$MAMBA_USER docker/_entrypoint.sh /usr/local/bin/_entrypoint
EXPOSE 8000
ENTRYPOINT [ "/usr/local/bin/_entrypoint" ]

# ---- manage runtime: the management CLI (render / recount / bidslake …) ----
FROM runtime-base AS runtime-manage
ENTRYPOINT [ "manage" ]
CMD ["--help"]

# ---- select the runtime by ENVIRONMENT; last stage is the default build target ----
FROM runtime-${ENVIRONMENT} AS final
