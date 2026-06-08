# syntax=docker/dockerfile:1-labs

ARG PIXI_VERSION=0.70.1
ARG BASE_IMAGE=ubuntu:24.04
ARG ENVIRONMENT=default
ARG DEBIAN_FRONTEND=noninteractive

FROM ubuntu:24.04 AS builder

# need to specify the ARG again to make it available in this stage
ARG PIXI_VERSION
ARG ENVIRONMENT

# doing this complicated double-build because we need git
# for creating pixi environments that depend on pypi packages installed 
# with git
RUN apt-get update && apt-get install -y curl git

# download the musl build since the gnu build is not available on aarch64
RUN curl -Ls \
	"https://github.com/prefix-dev/pixi/releases/download/v${PIXI_VERSION}/pixi-$(uname -m)-unknown-linux-musl" \
	-o /pixi && chmod +x /pixi
RUN /pixi --version

WORKDIR /app
COPY --parents ./pixi.lock ./pyproject.toml ./src/dirt ./src/django_dirt_ratings /app/
RUN /pixi install -e ${ENVIRONMENT} --locked 

FROM $BASE_IMAGE

ARG ENVIRONMENT
ARG MAMBA_USER=mambauser
ARG MAMBA_USER_ID=57439
ARG MAMBA_USER_GID=57439
ENV MAMBA_USER=$MAMBA_USER
ENV MAMBA_USER_ID=$MAMBA_USER_ID
ENV MAMBA_USER_GID=$MAMBA_USER_GID

COPY --chmod=0544 docker/_dockerfile_initialize_user_accounts.sh /usr/local/bin/_dockerfile_initialize_user_accounts.sh
RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh

# difficult
RUN apt-get update && apt-get install -y memcached

USER $MAMBA_USER

WORKDIR /app
COPY --from=builder --chown=$MAMBA_USER:$MAMBA_USER /app /app

ENV TZ=America/Chicago
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# from pixi shell-hook -e prod
ENV PATH=/app/.pixi/envs/${ENVIRONMENT}/bin:$PATH
ENV CONDA_PREFIX=/app/.pixi/envs/${ENVIRONMENT}

COPY --chmod=0544 --chown=$MAMBA_USER:$MAMBA_USER docker/_entrypoint.sh /usr/local/bin/_entrypoint

# Expose the Django port
EXPOSE 8000
ENTRYPOINT [ "/usr/local/bin/_entrypoint" ]