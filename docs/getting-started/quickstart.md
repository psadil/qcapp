# Quickstart

This walkthrough stands up DIRT against a small bundled sample dataset so you can see the
whole flow — download, index, render, review — end to end. It mirrors what the
`devsetup` task does.

## Prerequisites

- [pixi](https://pixi.sh) installed.
- Docker (to run the web app).
- The AWS CLI is provided by the `manage` environment and is used to fetch the sample data
  from OpenNeuro (anonymous, no credentials needed).

## 1. Generate the sample database

```shell
pixi run devsetup
```

This single command:

1. downloads a two-subject subset of OpenNeuro [`ds007070`](https://openneuro.org/datasets/ds007070)
   into `data/ds007070-fmriprep/`,
2. writes a `dataset_description.json` so the indexer treats it as a derivative dataset,
3. indexes it with `bids2table` into `data/ds007070_index.parquet`,
4. applies database migrations and creates the cache table,
5. creates an admin user (`admin` / `admin`), and
6. renders QC images for masks, spatial normalization, surface localization, and field-map
   coregistration.

!!! note
    The sample has no diffusion data, so the DTI-fit step is intentionally skipped.

## 2. Build and run the web app

```shell
docker buildx build -t psadil/dirt --platform=linux/amd64 --provenance=true .
docker run --rm -it -v $PWD/db:/app/db --env-file=.env.docker -p 8000:8000 psadil/dirt
```

## 3. Review

Open <http://localhost:8000>. Select a processing step and start rating — ratings are saved
as you go, so you can stop at any time. You can also log into the admin at
<http://localhost:8000/admin> with `admin` / `admin` to browse the stored images and ratings.

New to the two review styles (clicking to mark vs. rating the whole image)? See
[Two kinds of review](../concepts/interaction-types.md).

Ready to point DIRT at your own data? Continue to
[Review a local dataset](../tutorials/review-local-dataset.md).
