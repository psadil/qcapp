# Spatial-normalization landmark ROIs

The spatial-normalization step overlays each normalized T1w with translucent
**landmark bands** — the rating protocol of
[Benhajali et al. 2020](https://doi.org/10.3389/fninf.2020.00007): anatomy
should fall inside wide "confidence band" ROIs, and the reviewer marks grid
cells where it escapes. This page explains where those bands come from, how
they are built per template space, and how to add a space.

## Per-structure sourcing (procedural first)

`django_dirt_ratings.management.ingest.rois` builds one labeled dseg + JSON
sidecar per `(space, cohort)`. Every structure that *can* be derived from the
target space's own assets is, so nothing is warped that doesn't have to be:

| structure | source | spaces |
|---|---|---|
| brain-outline band | dilate(4mm) XOR erode(4mm) of the TemplateFlow `desc-brain` mask (Benhajali's own construction) | any with a recipe |
| lateral ventricles, hippocampi | TemplateFlow Harvard-Oxford subcortical atlas (`atlas-HOSPA`, `desc-th25`), labels verified by center-of-mass guards | 2009cAsym, NLin6Asym |
| sulcal/fissure/tentorium bands | hand-drawn Benhajali landmarks (no atlas defines these), shipped on the canonical `MNI152NLin2009cAsym` grid; warped per space through a dirt-built transform artifact | canonical + registered spaces |

The canonical hand-drawn landmark image is built once by
`tools/make_landmarks.py` from
[SIMEXP/brain_match](https://github.com/SIMEXP/brain_match) (MIT, pinned
commit) and committed with full provenance
(`src/django_dirt_ratings/data/PROVENANCE.md` and the sidecar JSON). The
original drawings live on the ICBM 2009a *symmetric* template; the build moves
them to `MNI152NLin2009cAsym` with a dipy affine+SyN registration on
gray-matter probability maps, gated on improving the within-brain GM
correlation over identity placement (0.845 → 0.965). The result of that warp is
shown on the [Landmark warp QC](landmark-warp-qc.md) page for visual
verification.

## Transforms are built once, validated, and recorded

Getting spaces right is the hard part, so every warp leaves evidence:

- **A cached transform artifact per space**: for a non-canonical space,
  `rois.build_rois` registers the canonical template's masked T1w to the
  target's (dipy affine(MI) + SyN(CC)) **once per transform version** and
  serializes the result as an ITK displacement-field
  `tpl-<space>_from-MNI152NLin2009cAsym_mode-image_*_xfm.h5` in the cache — a
  standard-format file that SimpleITK and ANTs apply directly, with its own
  JSON sidecar (engine, parameters, input sha256s, validation numbers). The
  serialization is validated before caching: applying the h5 must reproduce
  the direct dipy warp. Landmark labels are then warped through the h5 with
  nearest-neighbour interpolation, and every build re-checks the application:
  it **fails** unless warping improves the masked-T1w correlation over plain
  world-coordinate resampling — a mis-applied transform cannot slip through
  silently.
- **Why not TemplateFlow's published `*_xfm.h5` composites?** They were
  evaluated, and the file dirt needs is defective upstream:
  `tpl-MNI152NLin6Asym_from-MNI152NLin2009cAsym_mode-image_xfm.h5` encodes the
  *opposite* mapping — applied as named (by ANTs, SimpleITK, and nitransforms
  alike, all agreeing to four decimals) it *lowers* masked-T1w correlation
  below identity (0.64 vs 0.75), while it works only in the reverse role. The
  reverse-named file is healthy, and the numerical inverse of that healthy
  transform agrees closely with dirt's own registration — the
  [Landmark warp QC](landmark-warp-qc.md) page quantifies the comparison,
  band by band. Building our own keeps one validated engine (the same dipy
  pipeline that placed the landmarks on the canonical grid) until upstream
  ships a corrected file.
- **Provenance**: the artifact sidecar records the algorithm version, band
  width, per-structure source, every input file's sha256, the transform
  artifact's sha256 and version, and the r-improvement numbers. Post-warp
  label cleanup (one closing + largest component, to repair nearest-neighbour
  raggedness) is recorded per structure and refuses to change any structure by
  more than 10%.

## Cache and offline clusters

Artifacts land in `~/.cache/dirt/rois` (override with `DIRT_ROI_CACHE`), named
with the algorithm version so bumping `ROI_ALGORITHM_VERSION` invalidates
stale files without deleting anything. TemplateFlow downloads go to its own
cache (`TEMPLATEFLOW_HOME`).

Building needs the network (TemplateFlow) and, for non-canonical spaces with a
cold cache, a few minutes of registration — run once per transform version,
after which the cached `*_xfm.h5` is reused. Offline compute nodes therefore
**pre-warm on a login node**:

```bash
pixi run -e manage manage build_rois MNI152NLin2009cAsym MNI152NLin6Asym
```

then ship or share the cache directory. During `manage render`, discovery
groups anchors by their `space`/`cohort` entities and resolves each group's
artifact once; a space whose ROIs cannot be built is skipped with a warning —
never a guessed overlay.

## Display

The renderer collapses left/right structures into one hue per structure type
(the Okabe-Ito colorblind-safe palette, whose eighth entry is black and would
vanish on the dark background — the tentorium takes a violet from IBM Design's
set instead), draws the labels as a translucent fill with nearest-neighbour
resampling over the **skull-stripped** T1w (the same-space `desc-brain` mask is
a required sibling in discovery), and reads the per-space display cuts from the
artifact sidecar — derived from fixed fractions of the template's brain-mask
bounding box, calibrated to reproduce the historical MNI cut coordinates.

**The field of view is pinned to the landmarks.** nilearn frames a figure from
the union of everything drawn on it, so a subject whose brain escapes the bands
— exactly the failure under review — used to zoom the figure *out* around its
own error, shrinking the misalignment on screen. Every axis is therefore
clamped to the landmark image's own bounding box (`render._roi_bounds`), which
is constant per space. Every subject in a space is then framed identically, to
each other and to the reference figures below.

**Reference figures.** The rating page shows the matching template slice beside
each image: same space, same cut, same frame, with every band visible in that
slice named in place. They are per space rather than per subject, so
`pixi run -e dev reference-images` renders them once — through this same
renderer, over the space's own TemplateFlow T1w — and commits them under
`src/django_dirt_ratings/static/ratings/reference/`. The web process carries
only Django and could not draw them on demand; `django_dirt_ratings.reference`
maps a served image's recorded `space` to its figure, and shows no panel at all
rather than a mismatched one. The same tool builds the labeled montage on the
[rater tutorial](../tutorials/rate-spatial-normalization.md).

## Adding a space

1. Add the space to `rois._RECIPES` (one line) — this is a reviewed change,
   deliberately.
2. Check the assets: the space needs a TemplateFlow `desc-brain` mask and T1w;
   ventricles/hippocampi additionally need `atlas-HOSPA` (or extend the recipe
   with another documented route).
3. Run `manage build_rois <space>` — the first build registers the canonical
   template to the new space and caches the transform artifact — and inspect
   the built dseg over the template T1w before trusting it.
4. Run `pixi run -e dev reference-images` and commit the new space's figures,
   adding it to `reference.SPACES`. A test pins that list to `_RECIPES` and to
   the files on disk, so a space cannot gain a recipe and quietly lose its
   reference panel.
