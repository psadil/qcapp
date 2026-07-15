# How data flows

DIRT separates a heavy, occasional **image-generation** step from a light, always-on
**review** step. Understanding where the boundary sits explains most of the project's
structure.

```
preprocessed dataset (BIDS derivatives)
        │
        │  index            bids2table / bidslake  →  a catalog of derivative files
        ▼
   image generation         the `manage` environment (nibabel, nilearn, dipy, matplotlib)
        │                    renders a compact set of QC figures per derivative
        ▼
   SQLite database          each figure is stored as PNG/APNG bytes on an `Image` row
        │
        │  serve            the `default` environment (Django + HTMX), no neuro stack
        ▼
   reviewer's browser        one image at a time; ratings written back to the database
```

## The two environments (and two Docker images)

- **Image generation** runs in the `manage` pixi environment / the `psadil/dirt:manage`
  Docker image. This is the only place the neuroimaging libraries are installed. It reads
  files from disk, renders figures, and writes `Image` rows.
- **Review** runs in the `default` pixi environment / the `psadil/dirt` Docker image. It
  imports no neuroimaging code at all: it only reads pre-rendered image bytes out of the
  database and records ratings.

This split is why a reviewer can run DIRT on a laptop with nothing but the web container,
and why the expensive rendering can happen once, on a credentialed cluster node, ahead of
time.

## Layering inside the app

The web app follows the [HackSoft Django Styleguide](https://github.com/HackSoftware/Django-Styleguide):

- **selectors** (`selectors.py`) are the read side — they answer "which image next?" and
  fetch rows.
- **services** (`services.py`) are the write side — the only layer that creates or updates
  rows, always validating with `full_clean`.
- **views** and the **django-ninja API** are thin: they translate HTTP to selector/service
  calls.

Image generation delegates all database writes to the same services layer, so there is one
place that writes each kind of row.
