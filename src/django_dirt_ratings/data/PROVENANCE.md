# Provenance: canonical landmark image

`tpl-MNI152NLin2009cAsym_desc-landmarks_dseg.nii.gz` — hand-drawn landmark bands from Benhajali et al. 2020
(doi:10.3389/fninf.2020.00007), fetched from
[SIMEXP/brain_match](https://github.com/SIMEXP/brain_match) (MIT) at commit
`58476047cf43b30425eb35cb414890ce99c318c0`, built 2026-08-24 by
`tools/make_landmarks.py`. Full per-structure detail (source files, sha256s,
cleanup voxel counts) lives in the sidecar JSON next to the image.

## Why these sources

The raw per-structure drawings (`data/Misc/landmarks/*.nii.gz`) are each a
single connected component with zero interior holes. The previously bundled
mask derived instead from brain_match's degraded composite
(`mask_layout/mask_all_layout.nii.gz`: 48 fragments, 436 hole voxels)
resliced across mismatched grids (their 197x233x189 ICBM-09a grid vs the
193x229x193 2009c grid), which produced the fragmented, holey overlay this
replaces. Right-side structures are the left drawings mirrored across x=0,
exact on the symmetric template (brain_match's own right-side layout masks
are identical mirrors).

## Space

The drawings live on the ICBM 2009a *symmetric* template. They were moved to
`MNI152NLin2009cAsym` by dipy 1.12.1 affine(MI)+SyN(CC) on GM probability maps, gated on improving the
within-brain GM correlation over identity world-coordinate placement:
identity r = 0.845, warped r = 0.9651.
(Identity placement is already close — brain-mask Dice 0.989, mean surface
distance 0.5 mm — and the bands are ~10 mm wide, so the registration is a
refinement, not a rescue.)

TemplateFlow's curated inter-template `*_xfm.h5` composites were evaluated
for the per-space warps and rejected: applied through nitransforms they
*lowered* masked-T1w correlation below identity (0.66 vs 0.78 for
MNI152NLin6Asym), indicating a displacement-field convention mismatch, so
`management/ingest/rois.py` computes and validates its own dipy
registrations instead.

## Regenerating

```bash
pixi run -e dev python tools/make_landmarks.py
```
