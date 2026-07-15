"""Export the django-ninja OpenAPI schema and a rendered reference page.

Run in the lightweight ``docs`` (or ``dev``) pixi environment — it imports only
the web app (django-ninja), never the neuro stack. Writes:

- ``docs/api/openapi.json`` — the raw schema, for programmatic consumers.
- ``docs/reference/api.md`` — a Redoc page (spec inlined) plus a plain-Markdown
  endpoint table, so the REST reference regenerates from the live API code.

This is the automated REST-API scaffolding the plan calls for; it is chained
ahead of the Zensical build by ``pixi run -e docs docs-gen``.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from django_dirt_ratings.api import api

REDOC_CDN = "https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"


def _endpoint_table(schema: dict) -> list[str]:
    """A plain-Markdown table of endpoints (works with JS disabled)."""
    rows = ["| Method | Path | Summary |", "| --- | --- | --- |"]
    for path, methods in sorted(schema.get("paths", {}).items()):
        for method, op in sorted(methods.items()):
            summary = op.get("summary", "").replace("|", "\\|")
            rows.append(f"| `{method.upper()}` | `{path}` | {summary} |")
    return rows


def _render_page(schema: dict) -> str:
    # Inline the spec so Redoc needs no runtime fetch (robust to any base path).
    spec = json.dumps(schema).replace("</", "<\\/")
    lines = [
        "# REST API",
        "",
        "*Auto-generated from the django-ninja API by `manage export_openapi` — "
        "do not edit by hand.*",
        "",
        "The live app also serves interactive docs at `/api/docs`. The raw schema "
        "is published alongside this site at `api/openapi.json`.",
        "",
        *_endpoint_table(schema),
        "",
        '<div id="redoc-container"></div>',
        f'<script src="{REDOC_CDN}"></script>',
        "<script>",
        f"  Redoc.init({spec}, {{}}, document.getElementById('redoc-container'));",
        "</script>",
        "",
    ]
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Export the django-ninja OpenAPI schema and REST reference page."

    def handle(self, *args, **options) -> None:
        repo = settings.BASE_DIR.parent
        schema = dict(api.get_openapi_schema())

        api_dir = repo / "docs" / "api"
        ref_dir = repo / "docs" / "reference"
        api_dir.mkdir(parents=True, exist_ok=True)
        ref_dir.mkdir(parents=True, exist_ok=True)

        (api_dir / "openapi.json").write_text(json.dumps(schema, indent=2) + "\n")
        (ref_dir / "api.md").write_text(_render_page(schema))
        self.stdout.write(
            self.style.SUCCESS("Wrote docs/api/openapi.json and docs/reference/api.md")
        )
