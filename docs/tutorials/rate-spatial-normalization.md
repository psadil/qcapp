# How to rate spatial normalization

Spatial normalization warps each participant's brain onto a standard template
so that brains can be compared across people. Sometimes the warp fails — the
brain ends up shifted, tilted, or the wrong size — and those images need to be
caught before analysis.

Every image you'll see is the participant's brain **after** normalization, with
colored **landmark bands** drawn from the template it was aligned to: a sky-blue
band along the brain outline, plus bands for a few internal structures
(ventricles in orange, and sulci in other hues). The bands are wide on purpose —
they are the *tolerance*, not the target.

> **The one rule: anatomy should fall inside its band.** The brain edge should
> run through the blue band all the way around, and each internal structure
> should sit inside its colored band. When anatomy escapes a band, mark those
> grid cells.

The grid on each image is how you answer. Tap a cell to mark it, or drag to
paint a swath. Press <kbd>u</kbd> before clicking to mark cells **unsure** (amber),
<kbd>f</kbd> for **fail** (red), and <kbd>enter</kbd> to submit. An image with no marked
cells counts as a pass.

## A good normalization — leave everything unmarked

The brain edge runs inside the blue outline band everywhere, the ventricles sit
in their orange bands, and each sulcal band covers its sulcus. Nothing to mark:
just press <kbd>enter</kbd>.

![A well-normalized brain: every structure inside its band](../assets/tutorial/spatial_normalization/good.avif)

## Shifted brain — mark the cells where anatomy escapes

Here the whole brain is displaced. The edge crosses out of the blue band at the
front and pulls away from it at the back (and the internal structures sit
off-center in their bands too).

![A shifted brain, before marking](../assets/tutorial/spatial_normalization/bad_translation.avif)

Paint **fail** over every cell where the brain edge escapes its band — like
this:

![The same shifted brain with fail cells painted](../assets/tutorial/spatial_normalization/bad_translation_marked.avif)

## Tilted brain

A rotation shows up best on the side view: the brain edge dips out of the
outline band on opposite corners (here, out at the top-front and bottom-back).

![A tilted brain, before marking](../assets/tutorial/spatial_normalization/bad_rotation.avif)

Mark the cells along both violated edges:

![The same tilted brain with fail cells painted](../assets/tutorial/spatial_normalization/bad_rotation_marked.avif)

## Wrong size

When the normalization gets the scale wrong, the brain overflows (or rattles
around inside) the outline band *all the way around*, and the internal
structures miss their bands everywhere at once.

![An oversized brain, before marking](../assets/tutorial/spatial_normalization/bad_scale.avif)

![The same oversized brain with fail cells painted](../assets/tutorial/spatial_normalization/bad_scale_marked.avif)

## Subtle problems — use unsure

Often the misalignment is small: the edge slips just past the band in a few
places while everything else looks fine. That's what **unsure** (<kbd>u</kbd>,
amber) is for — mark the few cells you'd want a second opinion on and move on.
Don't agonize; unsure is a real answer.

![A subtly shifted brain with a few unsure cells painted](../assets/tutorial/spatial_normalization/unsure_subtle_marked.avif)

## Ready to rate

- Anatomy inside every band → press <kbd>enter</kbd>, nothing to mark.
- Anatomy outside a band → paint those cells with <kbd>f</kbd>.
- Borderline → paint the questionable cells with <kbd>u</kbd>.
- Something else wrong with the picture itself (artifacts, missing data)? Tick
  "I suspect there might be a problem with the image quality" on the form.

Don't worry about being perfect — images are reviewed by more than one rater,
and you can always come back to this page from the **Tutorial** link in the
app's navigation bar.
