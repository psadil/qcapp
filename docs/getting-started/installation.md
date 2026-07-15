# Installation

DIRT is split into two worlds that stay deliberately separate:

- a **web app** — a lightweight Django/HTMX service that serves pre-rendered QC images and
  records ratings. It needs no neuroimaging libraries.
- an **image-generation** step — a batch job that reads a preprocessed dataset and renders
  the QC figures into the database. This pulls in the heavy neuroimaging stack
  (nibabel, nilearn, dipy, matplotlib, …).

Keeping them apart means reviewers only ever run the small web app, and the neuro stack is
needed only when (re)generating images. See [How data flows](../concepts/data-flow.md).

## With pixi (development)

The project uses [pixi](https://pixi.sh) to manage environments. Four environments are
defined in `pyproject.toml`:

| Environment | Purpose |
| --- | --- |
| `default` | the web app runtime |
| `dev` | `default` plus test/lint tooling (`pixi run -e dev test`) |
| `manage` | the image-generation stack (nibabel, nilearn, dipy, bids2table, …) |
| `docs` | this documentation site (Zensical) |

Install an environment with, for example:

```shell
pixi install -e manage
```

## Configuration (`.env`)

Every setting is an environment variable read by `src/dirt/settings.py`. Copy the example
and fill in at least a secret key:

```shell
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The most important variables:

- `DJANGO_SECRET_KEY` (required)
- `DB` — path to the SQLite database file (default: `<repo>/db/dirt.db`)
- `CACHE_DB` — path to the cache database (default: `cache.sqlite3` next to `DB`)

See [`.env.example`](https://github.com/psadil/dirt/blob/main/.env.example) for the full list.

## With Docker

Two images are built from this repo:

- **`psadil/dirt`** — the web app. Serves the reviewer UI.
- **`psadil/dirt:manage`** — the image-generation CLI (the `manage` environment).

```shell
docker buildx build -t psadil/dirt --platform=linux/amd64 --provenance=true .
docker run --rm -it -v $PWD/db:/app/db --env-file=.env -p 8000:8000 psadil/dirt
```

The `db/` directory holds the SQLite database and its WAL sidecar files; mount it as a
volume so data survives the container. See [Deployment](../deployment.md) for production notes.
