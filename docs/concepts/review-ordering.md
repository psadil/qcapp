# Review ordering

There are often far more targets to review than budgets allow, and so it would be ideal to focus on just those cases that benefit most from human discernment. Put another way, the order in which images are served matters, and some orders may be more efficient than others. To accommodate this, DIRT's ordering is configurable.

## Strategies

A plan picks one strategy (`ordering.py`). All three are a single covering index seek.

| Strategy | Next image | Use |
|---|---|---|
| `breadth_first` (default) | fewest reviews first | one look at everything, then deepen |
| `anomaly_first` | fewest reviews first, then **most atypical** within a review-depth band | surface likely failures early, full coverage |
| `triage` | `anomaly_first` restricted to under-reviewed images | a quick failure hunt that *finishes* |


## The review plan (`dirt.toml`)

A plan is a small TOML file. It says which steps are reviewed, how to order them, and what to measure:

```toml
name = "ds007070 QC"

[ordering]
strategy = "anomaly_first"      # breadth_first | anomaly_first | triage
triage_depth = 1                # triage only

[steps.masks]                   # one block per step in the review
order_by = "volume_mm3"         # a measure below → the ordering key (omit ⇒ breadth-first here)
direction = "two_sided"         # two_sided | higher_worse | lower_worse
subgroup = ["space"]            # score within the same template space
min_cv = 0.01                   # optional: ignore subgroups varying < 1% (default)
# min_spread = 10000.0          # optional: absolute noise floor, in the measure's units

  [[steps.masks.measures]]      # what to MEASURE at ingest
  name = "volume_mm3"
  compute = "mask_volume"       # a metric DIRT computes itself

[steps.fmap_coregistration]     # order coregistrations worst-alignment first
order_by = "coreg_mm"
direction = "higher_worse"      # a bigger induced displacement is more suspect

  [[steps.fmap_coregistration.measures]]
  name = "coreg_mm"
  compute = "affine_displacement"   # RMS mm the coregistration affine moves the brain

  [[steps.fmap_coregistration.measures]]   # a metric from ANOTHER dataset (an MRIQC IQM)
  name = "fd_mean"
  catalog = "fd_mean"                       # the metadata key on the sibling record
  catalog_suffix = "bold"                   # the sibling MRIQC record's suffix
  match = ["sub", "ses", "task", "run"]     # entities that pair the two records
```

Each measure has exactly one source: `compute` (a metric DIRT computes over the source files) or `catalog` (a metric read from the bidslake catalog). Two computed extractors ship today:

- `mask_volume` — brain-mask volume in mm³ (comparable across voxel sizes; two-sided).
- `affine_displacement` — how far a coregistration affine moves the brain, in mm (Jenkinson RMS over the brain).

A `catalog` measure with `catalog_suffix` + `match` is cross-dataset: the metric is read from a record in a sibling dataset (see the bidslake [cross-dataset links](https://github.com/psadil/bidslake)), paired to this file by the `match` BIDS entities. That is how MRIQC IQMs (which live in a separate dataset) order an fMRIPrep review without the unsound cross-dataset entity join: DIRT only trusts the pairing because the shared source guarantees `sub-01` is the same subject in both. A missing or ambiguous match scores nothing (never a guess), so those images just fall back to the review's other ordering.

### Workflow

```shell
bidslake index -i derivatives -o study.duckdb   # build the catalog (+ --adapter <name> if any dataset in it needs one — pass the union on every run)
manage plan dirt.toml                            # validate → persist → activate the plan
manage render study.duckdb                       # render + measure (stamps Image.review_plan)
manage prioritize                                # measures → Image.priority (z-scores)
# ...then serve; the web app reads the active plan from the database.
```

`manage prioritize` is a safety valve like `recount`: rerun it after new data arrives.

### Provenance

A plan has two facets stored in their natural homes. The pipeline facet (measures, ordering key) shapes the images: `render` stamps each `Image.review_plan` and `manage prioritize` writes `Image.priority`. The serving facet (strategy, triage_depth) shapes a session: it is pinned onto each `Session` at start-up, so editing the plan mid-review never disturbs an in-flight session. Together they answer "what QC was done for this dataset?" from the database alone.

## Quality is a signal, not a verdict

Quality ratings are imperfect, and an outlier metric does not necessarily imply a bad scan. DIRT therefore treats a metric as a place that deserves attention, never a decision:

- `priority` only ever *reorders*; it never filters, hides, or rejects an image.
- Volume-like measures are **two-sided** by default (`|z|`): an atypically large *or* small brain mask is equally worth a look.
- A subgroup with no variation gets `priority = 0.0` (typical), not a flag.
- The metric is invisible to raters, so it cannot anchor their judgment; only researchers see it
  (in the admin).

In the language of statistical process control, distinguish special-cause variation (worth investigating) from common-cause variation (the normal spread), and score within a rational subgroup (e.g., a native-space mask volume is not comparable to an MNI-space one). That is, DIRT ranks rather than hard-thresholding at ±3σ.

## How `priority` is computed

The statistical unit is one target, which may comprise multiple rendered views (e.g., 5 slices along each of 3 axes). So, measures are de-duplicated per file before any statistic is taken.

There are two additional considerations.

1. "Does this subgroup vary enough to rank at all?" This matters mostly in cases where differences between the targets in a dataset are negligible. For example, brain masks resampled to `MNI152NLin2009cAsym` may be nearly identical (e.g., see `ds001761`). We get a floor using `sd / |mean|` (`min_cv`, default 1%; or an absolute `min_spread` in the measure's own units, which overrides it). Below the floor every member scores 0.0 (typical) and falls back to breadth-first.

2. "How unusual is this one?" — the *score*, using a robust modified z-score,
`0.6745 × (x − median) / MAD` ([Iglewicz & Hoaglin 1993]), falling back to the mean absolute deviation (`0.7979 × … / meanAD`) when MAD collapses to 0. Robust because a classic z divides by an sd that the outlier itself inflates (masking), and is hard-bounded at `(n-1)/√n` — just 1.5 for n = 4, so it saturates exactly when a scan is badly wrong. On the same real data the genuine +10.6% outlier scored classic |z| = 1.37 but robust |z| = 2.32.

## References

- Shewhart, W. A. (1931). *Economic Control of Quality of Manufactured Product.* Van Nostrand.
- Western Electric Co. (1956). *Statistical Quality Control Handbook.*
- Nelson, L. S. (1984). "The Shewhart Control Chart—Tests for Special Causes." *Journal of Quality Technology* 16(4):237–239.
- Deming, W. E. (1986). *Out of the Crisis.* MIT Press.
- Montgomery, D. C. *Introduction to Statistical Quality Control.* Wiley.
- Iglewicz, B., & Hoaglin, D. C. (1993). *How to Detect and Handle Outliers.* ASQC Basic References in Quality Control, Vol. 16. ASQC Quality Press — the robust modified z-score (MAD-based) DIRT uses for `priority`, and its mean-absolute-deviation fallback.
- Esteban, O., et al. (2017). "MRIQC: Advancing the automatic prediction of image quality in MRI from unseen sites." *PLOS ONE* 12(9):e0184661.
- Jenkinson, M., et al. (2002). "Improved optimization for the robust and accurate linear registration and motion correction of brain images." *NeuroImage* 17(2):825–841.
