# Order coregistrations by RMS displacement

This walkthrough puts the [review plan](../concepts/review-ordering.md) to work on a
concrete question: **of all the field-map coregistrations in a study, which ones should a
reviewer look at first?** We answer it by measuring how far each coregistration affine
actually moves the brain — its RMS displacement in millimetres — and serving the worst
alignments first.

It assumes you can already index and render a dataset (see
[Review a local dataset](review-local-dataset.md)). The only new piece is a small
`dirt.toml`.

## What we are ordering, and by what

The `fmap_coregistration` step renders, for each BOLD run, the reference EPI against the
coregistered boldref — masked and animated so a reviewer can flip between them and judge
the alignment by eye. fMRIPrep writes that alignment as a boldref→field-map affine
(`*_xfm.txt`). We want the runs whose affine is *most* out of place to rise to the top of
the queue.

The natural summary of "how badly does this affine move the brain?" is **not** the
determinant — that captures only volume scaling and is blind to translation and rotation, the
very errors a coregistration gets wrong. Instead DIRT's `affine_displacement` measure uses the
**RMS displacement** the transform induces over the brain
([Jenkinson et al. 2002](https://doi.org/10.1016/S1053-8119(02)91132-8)): for a voxel mapped
by `x → Mx + t`, with `A = M − I`, averaged over a sphere of radius `R` at the brain centroid
`c`,

```
E_rms = sqrt( (1/5) R² · tr(AᵀA) + |t + A c|² )   [mm]
```

which folds rotation, translation, and scale/shear into a single millimetre number. A run
that is coregistered well barely moves (`E ≈ 0`); a large `E` flags a suspect alignment. The
brain's centroid and radius come from the run's own brain mask, so the measure needs no
template.

## 1. Write the plan

Save this as `dirt.toml` next to your catalog:

```toml
name = "study coregistration QC"

[ordering]
strategy = "anomaly_first"        # fewest-reviews first, worst-aligned first within a depth band

[steps.fmap_coregistration]
order_by = "coreg_mm"             # the measure below becomes the ordering key
direction = "higher_worse"        # one-sided: a bigger displacement is more suspect

  [[steps.fmap_coregistration.measures]]
  name = "coreg_mm"
  compute = "affine_displacement" # RMS mm the coregistration affine moves the brain
```

Two choices are worth calling out, because they differ from the
[`mask_volume` example](review-local-dataset.md#4-order-by-quality-metrics-optional):

- **`direction = "higher_worse"`**, not `two_sided`. A mask can be atypical by being too big
  *or* too small, but a coregistration is only ever wrong by moving *too much* — there is no
  such thing as a suspiciously small displacement. So we score one-sided.
- **No `subgroup`.** Displacement is already a physical distance in millimetres, comparable
  across runs regardless of voxel size or template space, so there is no like-with-like
  grouping to do. (Volume needed `subgroup = ["space"]` because an MNI-space mask volume is
  not comparable to a native-space one.)

## 2. Index, plan, render, prioritize

The plan must be **active before you render**, because rendering is what stamps each image
with the plan and computes its measures:

```shell
pixi run -e manage bidslake index -i /path/to/derivatives/fmriprep -o study.duckdb
pixi run -e manage manage plan dirt.toml                        # validate → persist → activate
pixi run -e manage manage render study.duckdb --step fmap_coregistration
pixi run -e manage manage prioritize                            # measures → Image.priority
```

- `manage plan` parses and activates the plan, storing it in the database so it travels with
  the ratings.
- `manage render --step fmap_coregistration` renders just the coregistration images and, for
  each, computes `affine_displacement` from the run's brain mask and `*_xfm.txt`, stashing the
  raw millimetre value on the image.
- `manage prioritize` turns those raw measures into the ordering key: it converts each value
  to a robust z-score (how unusual this run is relative to the rest) and writes it to
  `Image.priority`. Rerun it after new data lands — it is a safe, idempotent recompute.

You can drop `--step fmap_coregistration` to render every step; the plan only orders the steps
it names, and everything else stays breadth-first.

## 3. Serve and review

```shell
docker run --rm -it -v $PWD/db:/app/db --env-file=.env -p 8000:8000 psadil/dirt
```

Open <http://localhost:8000>. On the first pass — every image unreviewed — `anomaly_first`
serves the whole set of coregistrations **worst-alignment first**, then naturally deepens to
give everything a look. The reviewer sees only the images; the millimetre metric is invisible
to them and cannot anchor their judgment. Researchers can see the raw value and the derived
priority in the admin.

!!! warning "A large displacement is a cue to look, not a verdict"
    `affine_displacement` never hides, filters, or rejects an image — it only decides who goes
    first. A big number can be a genuinely fine coregistration of an unusually-shaped head, and
    a small number can still hide a subtle failure. The measure buys you *attention order*, not
    a decision. See [Quality is a signal, not a verdict](../concepts/review-ordering.md#quality-is-a-signal-not-a-verdict).

## Where to go next

- Add a **cross-dataset** measure — order the same coregistrations by an MRIQC IQM (e.g.
  `fd_mean`) that lives in a *sibling* MRIQC dataset built from the same source. See the
  `catalog` / `catalog_suffix` / `match` example in
  [Review ordering](../concepts/review-ordering.md#the-review-plan-dirttoml).
- Switch `strategy` to `triage` for a failure hunt that *terminates* — it serves the worst
  under-reviewed image and stops when the pool empties.
