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
