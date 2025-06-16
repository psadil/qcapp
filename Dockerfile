FROM mambaorg/micromamba:2.0-ubuntu24.10

COPY --chown=$MAMBA_USER:$MAMBA_USER env.yml /tmp/env.yml

ARG MAMBA_DOCKERFILE_ACTIVATE=1
RUN micromamba install -q --name base --yes --file /tmp/env.yml \
    && rm /tmp/env.yml \
    && micromamba clean --yes --all

# Copy the project into the image
COPY . /opt/app
WORKDIR /opt/app

ENV TZ=America/Chicago
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

# Expose the Django port
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "python", "/opt/app/manage.py", "runserver", "--noreload", "0.0.0.0:8000"]
