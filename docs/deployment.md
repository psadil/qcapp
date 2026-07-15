# Deployment

DIRT is deliberately easy to stand up. It runs as a single container on one machine — a
laptop, a shared lab workstation, or a cluster login node — storing images and ratings in a
local SQLite database that needs no separate database server. It can also run on cloud
infrastructure behind a reverse proxy.

## Running the container

With a `.env` file providing at least `DJANGO_SECRET_KEY` (see
[Installation](getting-started/installation.md)):

```shell
docker run \
  --rm -it \
  -v ${PWD}/db:/app/db \
  --env-file=.env \
  -p 8000:8000 \
  psadil/dirt
```

On startup the container migrates the database, creates the cache table, and serves the app
with [granian](https://github.com/emmett-framework/granian). Open <http://localhost:8000>.

## SQLite in production

DIRT follows the
[alldjango guide to SQLite in production](https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production).
The database connection uses WAL journaling and `IMMEDIATE` transactions so multiple
workers can share the one file safely. The cache lives in its own SQLite file so ephemeral
data stays out of backups of the main database.

Because the whole application state is a directory of files, **back it up by copying the
mounted `db/` volume** (or replicate it continuously, for example with
[Litestream](https://litestream.io/)). The WAL sidecar files live in `db/` too, so mount
the whole directory as a volume for data to survive the container.

## Deploying behind a proxy

When `DJANGO_DEPLOYED=True`, the app enables secure cookies, HTTPS redirects, and honors
`X-Forwarded-Proto` (for running behind Traefik/Caddy/nginx). Set the public hostname(s):

```shell
DJANGO_DEPLOYED=True
DJANGO_ALLOWED_HOSTS=dirt.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://dirt.example.org
```

## Generating images at scale

Image generation is a separate, one-time-per-dataset job that runs in the
`psadil/dirt:manage` image (the neuroimaging stack). Render on a machine with access to the
data — often a credentialed cluster node — then serve the resulting `db/` anywhere. See
[Review a local dataset](tutorials/review-local-dataset.md) and
[`tools/write_imgs`](https://github.com/psadil/dirt/blob/main/tools/write_imgs) for a SLURM
example.
