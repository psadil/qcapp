# DIRT

## Running

The following assumes a file `.env` providing at least `DJANGO_SECRET_KEY`, and
optionally `DB` (the path to the SpatiaLite database file; defaults to
`db/dirt.db`). See [.env.example](.env.example) for the full list of variables.

The database and its WAL sidecar files live in a `db/` directory that must be
mounted as a volume so data survives the container:

```shell
docker run \
  --rm \
  -it \
  -v ${PWD}/db:/app/db \
  --env-file=.env \
  -p 8000:8000 \
  psadil/dirt
```

If all goes well, the container migrates the database, creates the cache table,
starts a Celery worker, and serves the app with granian:

```shell
Performing system checks...
System check identified no issues (0 silenced).
[INFO] Starting granian (dirt.asgi:application)
[INFO] Listening at http://0.0.0.0:8000
```

You should now be able to navigate to the app on a browser on your local machine: `http://localhost:8000`.

Select a processing step, and go rate! The ratings are saved as you go along, so you can exit at any time.

## Development Setup

For local testing and development, you can use the provided setup script to
automatically download a small sample dataset (from OpenNeuro `ds007070`),
create a database, and generate quality control images.

1. Run the setup script from the project root:
   ```shell
   pixi run devsetup
   ```
2. Build the Docker image:
   ```shell
   docker buildx build -t psadil/dirt --platform=linux/amd64 --provenance=true .
   ```
3. Run the development server via Docker (using your newly populated local database):
   ```shell
   docker run --rm -it -v $PWD/db:/app/db --env-file=.env.docker -p 8000:8000 psadil/dirt
   ```
4. Navigate to `http://localhost:8000`. You can log into the admin interface (`/admin`) using the username `admin` and password `admin`.

## Deployment notes

DIRT runs the database, the cache, and the Celery result store all on
SQLite/SpatiaLite in a single container, following
[the alldjango guide to SQLite in production](https://alldjango.com/articles/definitive-guide-to-using-django-sqlite-in-production).
The database connection uses WAL journaling and `IMMEDIATE` transactions so the
web workers and the Celery worker can share the one file. Because the whole
state is a directory of files, back it up (or replicate it, e.g. with
Litestream) by copying the mounted `db/` volume.

## Tips

### sqlite3

The dev database is a SpatiaLite file at `db/dirt.db`.

#### Check tables

```shell
$ sqlite3 db/dirt.db .tables
auth_group                        django_dirt_ratings_annotation
auth_group_permissions            django_dirt_ratings_image
auth_permission                   django_dirt_ratings_rating
auth_user                         django_dirt_ratings_session
auth_user_groups                  django_migrations
auth_user_user_permissions        django_session
django_admin_log                  spatial_ref_sys
django_content_type               ...
```

#### Look through some basic ratings

```shell
$ sqlite3 -header db/dirt.db "SELECT id, rating, source_data_issue, created_at, session_id, image_id FROM django_dirt_ratings_rating LIMIT 10;"
```

#### Look through location annotations

Clicked points are stored as geometries in `django_dirt_ratings_annotation`;
use SpatiaLite's `ST_X`/`ST_Y` to read pixel coordinates back out:

```shell
$ sqlite3 -header db/dirt.db "SELECT id, ST_X(geometry) AS x, ST_Y(geometry) AS y, image_id, session_id FROM django_dirt_ratings_annotation LIMIT 10;"
```

#### Get Ratings and Metadata

```shell
$ sqlite3 -header db/dirt.db "SELECT rating, file1 FROM django_dirt_ratings_rating LEFT JOIN django_dirt_ratings_image ON django_dirt_ratings_rating.image_id = django_dirt_ratings_image.id LIMIT 20;"
```

## Build

```shell
docker build -t psadil/dirt:prod --provenance=true --platform=linux/amd64 .
```

Note that we're not pushing this to dockerhub. Everything will be run locally.
