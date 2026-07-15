# Review a local dataset

This tutorial generalizes the [Quickstart](../getting-started/quickstart.md) to your own
preprocessed data sitting on a local disk (a laptop, a lab workstation, or a cluster
filesystem). The shape is always the same: **index → render → serve**.

## 1. Prepare the environment

```shell
pixi install -e manage
export DB=$PWD/db/dirt.db
export DJANGO_SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key as g; print(g())')"
pixi run -e manage manage migrate
pixi run -e manage manage createcachetable --database cache
```

Your derivatives directory should contain a `dataset_description.json` marking it as a
derivative dataset, e.g.:

```json
{
    "Name": "my-study-fmriprep",
    "BIDSVersion": "1.4.0",
    "DatasetType": "derivative",
    "GeneratedBy": [{"Name": "fmriprep"}]
}
```

## 2. Index the dataset

DIRT discovers derivatives through [bidslake](https://github.com/psadil/bidslake), which
builds a queryable DuckDB catalog of a dataset. Index once:

```shell
pixi run -e manage bidslake index -i /path/to/derivatives/fmriprep -o study.duckdb
```

## 3. Render the QC images

One command renders every step whose files are present in the catalog:

```shell
pixi run -e manage manage render study.duckdb
```

Useful flags:

- `--step masks` (repeatable) renders only the named step(s); the default is every step
  found. Choices: `masks`, `spatial_normalization`, `surface_localization`,
  `fmap_coregistration`, `dtifit`.
- `--update` re-renders image bytes in place, preserving any ratings already collected.
- `--sub` / `--res` filter to a subject label or resolution.
- `--workers` sets the number of render worker processes (default: CPU count).

`render` finds each derivative and its related files by BIDS concept — the brain mask's
same-space T1w, the field map's `IntendedFor` bold targets and their boldref / mask /
transform — rather than by string-matching filenames, so it is robust to the exact naming
a pipeline emits. Derivatives it can't resolve are skipped with a log line.

For a real cluster example (SLURM + `apptainer run docker://psadil/dirt:manage`), see
[`tools/write_imgs`](https://github.com/psadil/dirt/blob/main/tools/write_imgs).

!!! note "FreeSurfer and DTI-fit"
    `surface_localization` and `dtifit` read standardized but non-BIDS outputs
    (FreeSurfer `recon-all`, qsirecon FSL-dtifit). These are taught to bidslake with
    **adapters**; index those trees with the matching `bidslake index --adapter <name>`
    (see the bidslake docs) so `render` can discover them.

## 4. Serve and review

Point the web app at the same `db/` directory:

```shell
docker run --rm -it -v $PWD/db:/app/db --env-file=.env -p 8000:8000 psadil/dirt
```

Open <http://localhost:8000> and review. The reviewer never needs the neuro stack — the
images are pre-rendered and stored in the database.
