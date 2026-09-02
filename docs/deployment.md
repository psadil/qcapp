# Deployment

DIRT is deliberately easy to stand up, and it has two deployment shapes that share
one data model:

- **Local / self-hosted** — a single container (or `pixi run runserver`) on one
  machine: a laptop, a shared lab workstation, or a cluster login node. Images live
  as files under a local `media/` directory and rows in a local SQLite database; no
  network, no upload server. This is the whole story for a reviewer who receives a
  rendered `db/` + `media/` pair.
- **Remote** — the same container behind a reverse proxy on a small VM, with images
  delivered over the authenticated ingest API by `manage push` from wherever
  rendering happened.

## Local: running the container

With a `.env` file providing at least `DJANGO_SECRET_KEY` (see
[Installation](getting-started/installation.md)):

```shell
docker run \
  --rm -it \
  -v ${PWD}/db:/app/db \
  -v ${PWD}/media:/app/media \
  --env-file=.env \
  -p 8000:8000 \
  psadil/dirt
```

On startup the container verifies both volumes are real mounts, migrates the
database, creates the cache table, and serves the app with
[granian](https://github.com/emmett-framework/granian). Open
<http://localhost:8000> and log in — accounts are issued with:

```shell
pixi run -e manage manage create_rater alice
```

(from a checkout; `devsetup` creates a local `admin`/`admin` account. On the
deployed VM the same command runs inside the stack:
`export DIRT_HOST=$(vm-host)` once per shell, then
`docker compose exec dirt manage create_rater alice`.)

## SQLite + media in production

DIRT follows the
[alldjango guide to SQLite in production](https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production).
The database connection uses WAL journaling and `IMMEDIATE` transactions so multiple
workers can share the one file safely. The cache lives in its own SQLite file so ephemeral
data stays out of backups of the main database.

Rendered images are ordinary files under `media/` (content-addressed — see
`django_dirt_ratings/storage.py`), served by a login-required view with immutable
caching. The application state is therefore **two directories**: back up `db/`
(the ratings — the only irreplaceable data) with `sqlite3 ... "VACUUM INTO ..."`;
`media/` needs no backup wherever a `manage push` (or a re-render) can recreate
it.

## Remote: one VM, a shared caddy edge

The reference deployment serves dirt at `https://<host>/dirt/` beside another app
on one small VM (2 vCPU / 4 GB), with TLS terminated by a caddy container in a
separate compose stack (the `proxy` repo) that both apps join over an external
docker network:

```
proxy stack   caddy: ports 80/443; /dirt/* → dirt:8000 (prefix passed through,
              stripped only for /dirt/static/*), everything else → melrater:8000
dirt stack    deploy/compose.yaml — no ports, joins the `proxy` network
host layout   /srv/dirt/{db,media,backups,compose.yaml,.env,DEPLOYED}
```

- A fresh box is prepared once by the proxy repo's `bootstrap.sh` (docker,
  the `/srv` layout, this app's `.env` secret, the shared network), and the
  proxy's own deploy goes first — it installs the `vm-host` this deploy calls.
- `deploy/deploy.sh` runs from the laptop: build for linux/amd64, smoke-test,
  push to Docker Hub, rsync `deploy/compose.yaml`, `docker compose up -d` over
  ssh. The server never sees source or a build context.
- `/srv/dirt/.env` (chmod 600) holds exactly `DJANGO_SECRET_KEY`. The public
  address is not stored: `deploy.sh` exports `DIRT_HOST` from `vm-host`, the
  box's own answer for its own address (installed by the proxy repo), so
  `ALLOWED_HOSTS` cannot drift from the address the edge holds a certificate
  for — a drift that 400s every request while the `127.0.0.1` healthcheck
  still reports healthy.
- The container serves under the `/dirt` prefix via `DJANGO_FORCE_SCRIPT_NAME`;
  the proxy forwards the prefixed path through unstripped (Django strips it for
  routing), except for static requests, which caddy rewrites onto granian's
  `/static` route.
- `DJANGO_DEPLOYED=1` turns on secure cookies, the proxy-header trust, and the
  hardened django-axes address handling.

Accounts on the box (no superuser is created — `createsuperuser` is the one way
into `/admin/`):

```shell
export DIRT_HOST=$(vm-host)   # compose interpolates it; the deploy normally supplies it
docker compose exec dirt manage create_rater alice           # a reviewer
docker compose exec dirt manage create_rater pushbot --ingest  # an upload account
```

## Getting images onto a deployment

Rendering and serving stay decoupled: `manage render` writes only to the local
database and `media/` directory (A2CPS renders on cluster nodes with no network
at all), and `manage push` later reconciles that on-disk state against a
deployment from any networked machine:

```shell
manage push --server "https://$(ssh hetzner vm-host)/dirt" --user pushbot
```

The push is idempotent by content digest — units the server already holds
unchanged are skipped, review plans travel first, and a server-side `prioritize`
runs at the end — so re-running after a partial failure sends only what is
missing. The API is inert unless the deployment sets `DIRT_INGEST_ENABLED=1`,
and authenticates with HTTP Basic against an account in the `ingest` group.

## Generating images at scale

Image generation is a separate, one-time-per-dataset job that runs in the
`psadil/dirt:manage` image (the neuroimaging stack). Render on a machine with access to the
data — often a credentialed cluster node — then serve the resulting `db/` + `media/`
anywhere, or push them to a deployment. See
[Review a local dataset](tutorials/review-local-dataset.md) and
[`tools/write_imgs`](https://github.com/psadil/dirt/blob/main/tools/write_imgs) for a SLURM
example.
