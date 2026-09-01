# Data model

DIRT's database is small. Eight tables carry the whole review workflow; the full,
auto-generated field listing lives in the [Models reference](../reference/models.md).

## Entities

- **`Step`** — an enumeration of the processing steps DIRT can review: mask, spatial
  normalization, surface localization, field-map coregistration, T1w coregistration,
  DTI-fit. Each step knows its image type (a static or animated AVIF) and which
  interaction it uses.
- **`Image`** — one rendered QC figure: a reference to its media file (`img`, a
  content-addressed name under `MEDIA_ROOT` — see `storage.py`), its content digest, and
  the metadata that identifies it: the source file(s), the display orientation, the slice,
  and the step. A uniqueness constraint on `(slice, file1, display, step)` means
  re-rendering repoints a figure in place rather than duplicating it, preserving any
  ratings already attached; new bytes get a new file name, so a figure URL never changes
  what it means.
- **`Session`** — one reviewing session: which step, which user, when.
- **`MeasuredFile`** + **`Metric`** — the [measurements](metrics.md) taken of one source
  NIfTI, and the categorical context (`space`, `res`) they are compared within. They hang
  off the *file*, not the `Image`, because a file has many rendered views and one set of
  numbers. One `Metric` row per name; a NULL value means DIRT tried and could not measure,
  which is not the same as no row at all.

## Submissions

Two kinds of review submission hang off an `Image` and a `Session`:

- **`Rating`** — a whole-image judgement (`pass` / `unsure` / `fail`). Used by field-map
  coregistration and DTI-fit.
- **`Annotation`** + **`AnnotationCell`** — a click-to-mark submission. The `Annotation`
  records the grid used (`grid_cols`, `grid_rows`); each marked cell is an `AnnotationCell`
  (`col`, `row`, `rating`). A submission with no marked cells still records an `Annotation`
  — the reviewer looked and found nothing to mark. Used by masks, spatial normalization,
  and surface localization.

Both submission types also carry a `source_data_issue` flag (the reviewer suspects the
underlying image quality, not the preprocessing) and optional free-text `comments`.

## Why store rendered images?

Rendering is expensive and the neuro stack is heavy, so DIRT renders each figure once and
stores the result. Reviewers then load pre-rendered figures with no neuroimaging
dependencies. The bytes live as ordinary media files (served by a login-required view with
immutable caching, since each file's name embeds its content digest), while the database
row carries the identity and review state — which keeps the database small, lets images
travel to a deployment over the [ingest API](../reference/api.md), and leaves the ratings
as the only data that needs backing up. See [How data flows](data-flow.md).
