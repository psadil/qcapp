# Two kinds of review

Each derivative is reviewed with whichever interaction best matches how it tends to fail.

## Click to mark a location

For problems that show up in a specific spot — a mask that includes skull, a cortical
surface that strays into gray matter — the reviewer clicks directly on each problem area.
This produces a set of marked locations per image; more marks generally means lower
quality, and *where* the marks fall can hint at which parts of a derivative remain usable.

Used for **brain masks**, **spatial normalization**, and **surface localization**.

Internally, clicks are recorded on a grid overlaid on the image: each submission is an
`Annotation` (recording the grid it used) with one `AnnotationCell` per marked cell (its
`col`, `row`, and a `rating` of *unsure* or *fail*; unmarked cells are an implied *pass*).
See the [Data model](data-model.md).

## Rate the whole image

For problems that are not tied to one location — a globally noisy tensor-fit map, a
coregistration that failed to align two images — the reviewer chooses **pass**, **unsure**,
or **fail** (scored 0 / 1 / 2). A single *fail* can be enough to exclude a derivative.

Used for **field-map coregistration** and **diffusion tensor fitting**.

Each whole-image judgement is a `Rating` row.
