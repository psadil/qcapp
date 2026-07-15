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

```shell
pixi run -e manage b2t2 index --output my_index.parquet --workers 4 /path/to/derivatives/fmriprep
```

## 3. Render the QC images

Parquet-driven steps take the index; the FreeSurfer- and DTI-based steps point at a
directory:

```shell
pixi run -e manage manage add_masks my_index.parquet
pixi run -e manage manage add_spatial_normalization my_index.parquet
pixi run -e manage manage add_fmap_coregistration my_index.parquet
pixi run -e manage manage add_surface_localization /path/to/derivatives/freesurfer
pixi run -e manage manage add_dtifit /path/to/derivatives/qsirecon_fsl_dtifit/dtifit/multishell
```

Useful flags:

- `--update` re-renders image bytes in place, preserving any ratings already collected.
- `--res` filters to a specific resolution (masks and spatial normalization only).

For a real cluster example (SLURM + `apptainer run docker://psadil/dirt:manage`), see
[`tools/write_imgs`](https://github.com/psadil/dirt/blob/main/tools/write_imgs).

!!! warning "The current commands assume fMRIPrep naming"
    Image discovery today relies on specific filename conventions:
    `add_spatial_normalization` only picks up `space-MNI152NLin2009cAsym, desc-preproc`;
    `add_masks` expects a `desc-brain_mask` with a `desc-preproc_T1w` partner;
    `add_fmap_coregistration` expects `desc-preproc_fieldmap` / `desc-epi`, reads
    `IntendedFor`, and looks for a boldref→fieldmap transform;
    `add_surface_localization` needs `<sub>/mri/brain.mgz` + `ribbon.mgz`; and
    `add_dtifit` expects `*dwi_FA.nii.gz` with sibling `V1`/`V2`/`V3`. Derivatives that
    differ are silently skipped.

!!! note "Coming soon: bidslake"
    A refactor is underway to replace the separate index step and the five `add_*`
    commands with a single `manage render` command driven by
    [bidslake](https://github.com/psadil/bidslake), which discovers derivatives by BIDS
    concept rather than by filename string-matching. When it lands, steps 2–3 collapse to
    `bidslake index … --output study.duckdb` followed by `manage render study.duckdb`.

## 4. Serve and review

Point the web app at the same `db/` directory:

```shell
docker run --rm -it -v $PWD/db:/app/db --env-file=.env -p 8000:8000 psadil/dirt
```

Open <http://localhost:8000> and review. The reviewer never needs the neuro stack — the
images are pre-rendered and stored in the database.
