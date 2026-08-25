"""Export the ``dirt.toml`` review-plan JSON Schema.

The schema is generated from the pydantic models in :mod:`~django_dirt_ratings.plan`
— the same models :func:`~django_dirt_ratings.plan.parse` validates with — so it
cannot drift from what ``manage plan`` accepts. Writes ``docs/api/plan.schema.json``,
published alongside the docs site so editors (Even Better TOML, tombi) can validate
and complete plan files via a ``#:schema`` directive. Chained ahead of the Zensical
build by ``pixi run -e docs docs-gen``, like ``export_openapi``.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from django_dirt_ratings import plan

SCHEMA_ID = "https://psadil.github.io/dirt/api/plan.schema.json"


class Command(BaseCommand):
    help = "Export the dirt.toml review-plan JSON Schema."

    def handle(self, *args, **options) -> None:
        schema = plan.Plan.model_json_schema()
        schema = {
            # pydantic emits the 2020-12 dialect; stamp it plus the published $id.
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": SCHEMA_ID,
            "title": "DIRT review plan (dirt.toml)",
            **{k: v for k, v in schema.items() if k != "title"},
        }

        out = settings.BASE_DIR.parent / "docs" / "api"
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
        self.stdout.write(self.style.SUCCESS("Wrote docs/api/plan.schema.json"))
