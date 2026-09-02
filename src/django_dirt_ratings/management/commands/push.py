"""Push locally rendered units (and their review plans) to a deployment.

The local-first contract: `render` writes into the local SQLite database and
media directory with no network at all (A2CPS compute nodes have none), and
this command later reconciles that on-disk state against a deployment's ingest
API from any networked machine. Reconciliation is by digest pair — a unit is
skipped only when the server already holds the same image set (unit digest)
AND the same metrics/entities/plan provenance (meta digest) — so re-running
after a partial failure pushes only what is missing, and a re-measure with
byte-identical images still travels.

Order per run: every review plan the pushed units reference (the local active
plan last, so both sides end active on the same one), then the units, then one
server-side `prioritize` so the anomaly_first ordering keys are fresh.
"""

from __future__ import annotations

import io
import os
import typing as t

import orjson
import typer
from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django_typer.management import TyperCommand

from django_dirt_ratings import models, push, selectors, transfer


class Command(TyperCommand):
    def handle(
        self,
        server: t.Annotated[
            str | None,
            typer.Option(help="Deployment base URL (default: $DIRT_PUSH_URL)."),
        ] = None,
        step: t.Annotated[
            list[str] | None,
            typer.Option(
                help="Step cli name, repeatable (default: every step with images)."
            ),
        ] = None,
        user: t.Annotated[
            str | None,
            typer.Option(help="Ingest account name (default: $DIRT_PUSH_USER)."),
        ] = None,
        password_env: t.Annotated[
            str,
            typer.Option(help="Env var holding the push password (else a prompt)."),
        ] = "DIRT_PUSH_PASSWORD",
        dry_run: t.Annotated[
            bool, typer.Option(help="List what would be pushed, then stop.")
        ] = False,
    ) -> None:
        """Push locally rendered units to a deployment's ingest API."""
        base_url = server or os.environ.get("DIRT_PUSH_URL")
        if not base_url:
            raise typer.BadParameter("pass --server or set DIRT_PUSH_URL")
        username = user or os.environ.get("DIRT_PUSH_USER")
        if not username:
            raise typer.BadParameter("pass --user or set DIRT_PUSH_USER")

        steps = (
            [models.Step.from_cli_name(name) for name in step]
            if step
            else [
                models.Step(value)
                for value in models.Image.objects.values_list(
                    "step", flat=True
                ).distinct()
            ]
        )

        if dry_run:
            # No credentials needed to see what a push would consider.
            for step_enum in steps:
                for file1 in sorted(_local_units(step_enum)):
                    self.stdout.write(f"would consider {step_enum.cli_name}: {file1}")
            return

        password = os.environ.get(password_env) or typer.prompt(
            "password", hide_input=True
        )
        target = push.PushTarget(
            base_url=base_url, username=username, password=password
        )

        pushed, skipped, failures = 0, 0, []
        with push.open_client(target) as client:
            to_push: list[tuple[models.Step, str, _Unit]] = []
            for step_enum in steps:
                # The digest index comes from the same selector the server's
                # /units endpoint runs, so both sides compute it identically.
                local_index = {
                    row["file1"]: (row["unit_digest"], row["meta_digest"])
                    for row in selectors.unit_digests(step=int(step_enum))
                }
                local = _local_units(step_enum)
                remote = push.fetch_units(client, target, step=step_enum.cli_name)
                for file1, unit in sorted(local.items()):
                    if remote.get(file1) == local_index[file1]:
                        skipped += 1
                    else:
                        to_push.append((step_enum, file1, unit))

            _sync_plans(client, target, units=[unit for _, _, unit in to_push])

            for step_enum, file1, unit in to_push:
                try:
                    payload, tar = _build_unit(step_enum, file1, unit)
                    push.push_unit(client, target, payload=payload, tar=tar)
                except (push.PushFailed, OSError) as exc:
                    failures.append(f"{step_enum.cli_name}: {file1} — {exc}")
                else:
                    pushed += 1
                    self.stdout.write(f"pushed {step_enum.cli_name}: {file1}")

            if pushed:
                push.trigger_prioritize(client, target)

        self.stdout.write(
            self.style.SUCCESS(f"pushed {pushed} unit(s), {skipped} already current.")
        )
        if failures:
            raise CommandError(
                f"{len(failures)} unit(s) failed:\n" + "\n".join(failures)
            )


class _Unit(t.NamedTuple):
    """One local unit's rows, as the push needs them."""

    file2: str | None
    review_plan_id: int | None
    images: list[tuple[int, int | None, str, str]]  # display, slice, digest, name


def _local_units(step: models.Step) -> dict[str, _Unit]:
    """Every unit this step holds locally, keyed by ``file1``."""
    grouped: dict[str, list[tuple[int, int | None, str, str]]] = {}
    extras: dict[str, tuple[str | None, int | None]] = {}
    rows = models.Image.objects.filter(step=int(step)).values_list(
        "file1", "display", "slice", "digest", "img", "file2", "review_plan_id"
    )
    for file1, display, cut, digest, name, file2, plan_id in rows:
        grouped.setdefault(file1, []).append((display, cut, digest, name))
        extras[file1] = (file2, plan_id)
    return {
        file1: _Unit(
            file2=extras[file1][0],
            review_plan_id=extras[file1][1],
            images=images,
        )
        for file1, images in grouped.items()
    }


def _sync_plans(client, target: push.PushTarget, *, units: list[_Unit]) -> None:
    """Push every plan the units reference, ending on the local active plan.

    ``plan_apply`` activates whatever it is handed, so the local active plan
    goes last — both sides then agree on which plan is live, while older
    plans referenced by re-pushed units still exist for provenance.
    """
    referenced = {
        unit.review_plan_id for unit in units if unit.review_plan_id is not None
    }
    active = models.ReviewPlan.objects.filter(is_active=True).first()
    records = list(models.ReviewPlan.objects.filter(pk__in=referenced).order_by("pk"))
    if active is not None and active not in records:
        records.append(active)
    elif active is not None:
        records.remove(active)
        records.append(active)
    remote = push.fetch_plan(client, target)
    remote_hash = remote["content_hash"] if remote else None
    for record in records:
        if record.content_hash == remote_hash and record == records[-1]:
            continue
        push.push_plan(client, target, name=record.name, toml=record.toml)


def _build_unit(step: models.Step, file1: str, unit: _Unit) -> tuple[bytes, bytes]:
    """The two file parts for one unit: its JSON payload and its image tar."""
    measured = models.MeasuredFile.objects.filter(step=int(step), file1=file1).first()
    plan_hash = (
        models.ReviewPlan.objects.filter(pk=unit.review_plan_id)
        .values_list("content_hash", flat=True)
        .first()
        if unit.review_plan_id is not None
        else None
    )
    payload = orjson.dumps(
        {
            "step": step.cli_name,
            "file1": file1,
            "file2": unit.file2,
            "entities": measured.entities if measured else None,
            "metrics": dict(measured.metrics.values_list("name", "value"))
            if measured
            else {},
            "plan_hash": plan_hash,
            "images": [
                {"display": display, "slice": cut, "digest": digest}
                for display, cut, digest, _ in unit.images
            ],
        }
    )
    buffer = io.BytesIO()
    transfer.write_unit_tar(
        (
            (display, cut, default_storage.open(name).read())
            for display, cut, _, name in unit.images
        ),
        buffer,
    )
    return payload, buffer.getvalue()
