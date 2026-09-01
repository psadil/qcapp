# Metrics

DIRT measures every derivative it renders. Not the metrics a review plan asks for —
**every metric it can compute from the files a step happens to carry**. A metric worth
storing and a metric worth *ordering by* are different questions, and only the second
one belongs to the plan.

That has a practical consequence worth stating plainly: adding a metric to DIRT makes
it appear for every dataset on the next `manage render`, with no `dirt.toml` edit
anywhere. And a step that gains an input gains that input's metrics for free.

## What is measured, and when

Each extractor declares the input **roles** it needs. A job carries roles resolved at
discovery — a brain mask, the T1w it belongs with, a transform — and an extractor runs
if and only if the job carries all of its roles.

| Metric | Needs | Meaning | Direction |
|---|---|---|---|
| `mask_volume` | `mask` | Brain-mask volume in mm³ | two-sided |
| `fov_cutoff_dorsal` | `mask` | How much brain the superior frame face cuts | higher worse |
| `fov_cutoff_ventral` | `mask` | The same for the inferior face | higher worse |
| `fov_cutoff_max` | `mask` | The worst of all six frame faces | higher worse |
| `affine_displacement` | `mask`, `transform` | RMS mm a coregistration affine moves the brain (Jenkinson et al. 2002) | higher worse |
| `fov_cutoff_cortex` … `_cerebellum`, `_brainstem`, `_cerebral_wm` | `mask`, `dseg`, `dseg_labels` | Which tissue the frame cuts through | higher worse |
| `fov_excluded_cortex` … `_cerebellum`, `_brainstem`, `_cerebral_wm` | `mask`, `dseg`, `dseg_labels`, `boldref2anat` | What fraction of each structure the field of view missed | higher worse |

The names are the single source of truth for `order_by` in a review plan: they live in
`models.ComputedMetric`, the extractor registry is checked against that enum at import,
and the plan's [JSON Schema](https://psadil.github.io/dirt/api/plan.schema.json)
publishes them so editors can complete them.

## Field-of-view cutoff

In a large study some scans are acquired with a partial field of view: the top or
bottom of the brain falls outside the slice stack. ABCD screens for this automatically,
describing the measure as *"% intersection of brain mask with frame borders"* and
splitting it into a dorsal (superior) and a ventral (inferior) score.

DIRT computes, for each of the six faces of the image frame, the mask voxels lying in
that face's plane as a percentage of the brain's **widest cross-section along the same
axis**. 0 means the brain never reaches that face; 100 means it is cut at its widest.
The superior and inferior faces are found from the affine, never from array order, so
an `L/A/I` volume reports its dorsal score from index 0.

Normalizing by the brain rather than by the plane's area is deliberate. The obvious
alternative — percentage of the border plane that is brain — scales with how much empty
field of view surrounds the head, so a native-space mask in a generous 256 mm frame and
a tightly cropped template-space one would not be comparable. Since DIRT scores a metric
*within a rational subgroup*, comparability is the whole game.

!!! note "ABCD's thresholds are indicative, not transferable"

    ABCD publishes the wording but not the formula, and its pipeline (MMPS) is
    distributed only as compiled container images, so the denominator is unknown. Its
    recommended-inclusion cutoffs — dMRI dorsal `< 47`, ventral `< 54`; fMRI dorsal
    `< 65`, ventral `< 60`, chosen for a 0.05% false-alarm rate — are a useful sense of
    scale, not values to apply to DIRT's numbers. Note also that ABCD assesses FOV
    cutoff but deliberately keeps it *out* of its overall pass/fail recommendation,
    which is the same stance DIRT takes: [a signal, not a verdict](review-ordering.md).

## Which tissue is lost

How much is cut matters less than what. Losing some cerebellum is a nuisance; losing
cortex is not. Both questions use FreeSurfer's `aseg` segmentation, which fMRIPrep
writes as `desc-aseg_dseg.nii.gz` beside a `desc-aseg_dseg.tsv` label lookup — and DIRT
**verifies** that lookup rather than trusting the numbering: every index it uses must be
present and named as expected, so a relabelled segmentation fails loudly instead of
quietly scoring cerebellum as cortex.

The label table is a dataset-root file with no subject entities, so it is paired with a
segmentation by the indexed tree they share, not by subject.

**`fov_excluded_*` is an exact measurement.** A functional run acquired with a short
stack simply does not reach some of the brain, and the T1w — which covers the whole head
— knows each structure's true extent. Mapping the segmentation through the
`from-boldref_to-T1w` affine into the functional frame and counting what lands outside
gives a real percentage: *this run is missing 38% of the cerebellum*. Exclusion is
defined by the **frame**, not by the functional brain mask: tissue outside the
acquisition matrix was never sampled, whereas tissue inside the frame but missing from
the mask is signal dropout — a different question this metric does not conflate with
coverage.

**`fov_cutoff_<tissue>` is a proxy, by necessity.** When the *anatomical itself* is
short, the segmentation was derived from that same short image, so nothing downstream
can say how much tissue is missing: it was never imaged. What is measurable is the size
of the cut surface per structure — the field-of-view score above, computed over one
tissue at a time. A non-zero `fov_cutoff_cortex` means the frame is cutting through
cortex, which is what you wanted to know; it is not a fraction of the cortex lost.

## Where the values live

A measurement belongs to a NIfTI, not to a picture of one. A file has nine to fifteen
rendered views, so DIRT stores its numbers once, on a `MeasuredFile` row, with one
`Metric` row per name — real columns to group and aggregate in SQL rather than a JSON
blob repeated once per view. `manage prioritize` reads them; `manage render --update`
re-measures.

Absence and NULL mean different things, and the difference is worth keeping:

- **no row** — the extractor never applied to this file, because the job did not carry
  its roles. Most datasets have no `dseg`, so most files have no tissue metrics.
- **a NULL value** — the extractor ran and could not measure this file: an empty mask, a
  structure absent from the segmentation, a segmentation on a different voxel grid from
  the mask (nothing here is resampled, and a mismatched grid is never guessed at).

Values are never shown to raters — a metric that anchored someone's judgement would stop
being independent evidence. They are visible to researchers in the admin, under
`MeasuredFile`.
