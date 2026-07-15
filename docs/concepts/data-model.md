# Data model

DIRT's database is small. Six tables carry the whole review workflow; the full,
auto-generated field listing lives in the [Models reference](../reference/models.md).

## Entities

- **`Step`** — an enumeration of the processing steps DIRT can review: mask, spatial
  normalization, surface localization, field-map coregistration, DTI-fit. Each step knows
  its image type (PNG or animated APNG) and which interaction it uses.
- **`Image`** — one rendered QC figure, stored as bytes (`img`) together with the metadata
  that identifies it: the source file(s), the display orientation, the slice, and the step.
  A uniqueness constraint on `(slice, file1, display, step)` means re-rendering updates a
  figure in place rather than duplicating it, preserving any ratings already attached.
- **`Session`** — one reviewing session: which step, which user, when.

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
stores the bytes. Reviewers then read images straight from the database with no
neuroimaging dependencies. See [How data flows](data-flow.md).
