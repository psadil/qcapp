# Landmark warp QC

The hand-drawn sulcal landmark bands
([Benhajali et al. 2020](https://doi.org/10.3389/fninf.2020.00007), fetched from
[SIMEXP/brain_match](https://github.com/SIMEXP/brain_match)) were drawn on the ICBM
2009a *symmetric* template, but dirt ships them on the `MNI152NLin2009cAsym` grid
(see [Spatial-normalization ROIs](spatial-normalization-rois.md)). Moving them
required a one-time registration: TemplateFlow publishes no transform from the
2009a-symmetric release, so `tools/make_landmarks.py` computes a dipy
affine(MI)+SyN(CC) registration on the two templates' gray-matter probability
maps. This page shows the result so you can judge the warp yourself.

## The numbers

- The two templates are near-identical anatomy to begin with: brain-mask Dice
  0.989 and ~0.5 mm mean surface distance under plain world-coordinate placement.
- The registration is gated — it must improve within-brain GM correlation over
  identity placement, and it did: r 0.845 → 0.965.
- The bands are ~10 mm wide by design, so the warp is a refinement, not a
  rescue: residual registration error is far below the tolerance the rating
  protocol builds into the bands.
- Post-warp label cleanup (one closing + largest connected component, repairing
  nearest-neighbour raggedness) is recorded per structure in the sidecar and
  refuses to change any structure by more than 10%.

## The result

The composed landmarks over the TemplateFlow `MNI152NLin2009cAsym` T1w at the
display cuts used during review. A successful warp puts each band on the anatomy
it names: the central-sulcus bands ride the central sulcus (clearest on the
superior axial and lateral sagittal cuts), the cingulate bands follow the
cingulate sulcus above the corpus callosum, the calcarine and parieto-occipital
bands meet in the medial occipital lobe, and the tentorium bands lie along the
cerebellar tent. A failed warp would leave a band floating off its sulcus by
more than the band's own width — nothing subtle.

![Landmarks over the template T1w, sagittal cuts](../assets/concepts/landmarks/qc_landmarks_x.avif)

![Landmarks over the template T1w, coronal cuts](../assets/concepts/landmarks/qc_landmarks_y.avif)

![Landmarks over the template T1w, axial cuts](../assets/concepts/landmarks/qc_landmarks_z.avif)

## The second warp: to `MNI152NLin6Asym`

Reviewing normalization to `MNI152NLin6Asym` needs the landmarks in that space
too. dirt builds this warp the same way — dipy affine(MI)+SyN(CC) on the two
templates' masked T1ws — once per transform version, serialized as an ITK
`*_xfm.h5` artifact in the ROI cache and gated on improving masked-T1w
correlation over identity placement (0.745 → 0.935; see
[Spatial-normalization ROIs](spatial-normalization-rois.md)).

TemplateFlow publishes curated composites between these two spaces, but the
from-`MNI152NLin2009cAsym` file is mislabeled upstream (it encodes the
opposite direction). The *reverse*-named file is healthy, and its numerical
inverse (field-inversion round-trip error 0.004 mm) served as a fully
independent cross-check of dirt's warp — a different algorithm (TemplateFlow's
multi-channel ANTs registration over surrogate subjects) from a different
group. The two routes agree far inside the bands' ~10 mm tolerance
(measured 2026-08-25 on raw nearest-neighbour warps, before cleanup):

- The pull-back point maps disagree by 1.3 mm (median) over the 6Asym brain
  and 1.2 mm within the landmark bands (p95 4.1 mm). For scale: dirt's warp
  deforms by 2.3 mm on average, the inverted TemplateFlow one by 1.5 mm.
- Warped-T1w correlation with the 6Asym template: 0.935 (dirt) vs 0.857
  (inverted TemplateFlow); identity resampling scores 0.745.
- Band by band, dirt-warped vs inverted-TemplateFlow-warped landmarks:

| band | Dice L/R | ΔCOM mm L/R |
|---|---|---|
| central sulcus | 0.91 / 0.91 | 1.5 / 1.8 |
| cingulate sulcus | 0.90 / 0.92 | 2.2 / 1.6 |
| calcarine sulcus | 0.88 / 0.88 | 0.9 / 0.5 |
| parieto-occipital fissure | 0.93 / 0.92 | 0.8 / 1.1 |
| tentorium cerebelli | 0.91 / 0.93 | 1.1 / 0.8 |

Two independent routes placing every band's voxels within ~1–2 mm of each
other — an order of magnitude inside the band width — is the practical
assurance that landmark placement does not hinge on which of them you trust.

## Why dipy for this registration?

- dipy's `SymmetricDiffeomorphicRegistration` implements the SyN algorithm of
  [Avants et al. 2008](https://doi.org/10.1016/j.media.2007.06.004) — the same
  algorithm ANTs implements — per
  [dipy's SyN tutorial](https://docs.dipy.org/stable/examples_built/registration/syn_registration_3d.html),
  and the affine stage is dipy's multi-resolution mutual-information
  registration.
- Registering to an MNI ICBM 2009 template with this affine(MI)→SyN(CC)
  pipeline is an officially documented dipy use: the
  [streamline registration tutorial](https://docs.dipy.org/stable/examples_built/registration/streamline_registration.html)
  does exactly that, and dipy ships the ICBM 2009a and 2009c templates itself
  (`dipy.data.read_mni_template`).
- On quality, a
  [2026 DIPY benchmark](https://dipy.org/posts/2026/2026_06_22_Tomas.html) of
  100 OASIS-2 brain pairs put out-of-the-box dipy SyN within ~0.4% of ANTs SyN
  on image-similarity metrics.
- The honest caveat: no source certifies dipy SyN for *template-to-template*
  registration specifically. The defense is the task itself — near-identical
  same-series templates, a gated result, and the figures above.

## Regenerating

Re-render just the figures from the committed landmark image (fast, no
registration):

```bash
pixi run -e dev python tools/make_landmarks.py --figures-only
```

Rebuild everything from the brain_match sources (network + a few minutes of
registration):

```bash
pixi run -e dev python tools/make_landmarks.py
```
