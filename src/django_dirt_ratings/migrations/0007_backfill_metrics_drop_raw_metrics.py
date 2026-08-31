"""Move measurements off Image.raw_metrics and onto MeasuredFile/Metric.

The old blob was stored once per rendered view, so the same numbers repeated ~15
times per NIfTI; the new tables hold them once, keyed by the file they describe.
Values are carried over under whatever name the review plan gave them at the time,
which is what `prioritize` was ranking on — re-running `manage render --update`
adds the canonical names for everything DIRT now computes.
"""

from django.db import migrations

#: Keys the old blob used for rational-subgroup context rather than measurement.
ENTITY_KEYS = ("sub", "ses", "space", "res")


def _split(raw):
    """One old blob as ``(entities, values)``."""
    entities, values = {}, {}
    for key, value in (raw or {}).items():
        if key in ENTITY_KEYS:
            entities[key] = value
        elif value is None:
            values[key] = None  # measured, unmeasurable — not the same as absent
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            entities[key] = value
        else:
            values[key] = float(value)
    return entities, values


def backfill(apps, schema_editor):
    Image = apps.get_model("django_dirt_ratings", "Image")
    MeasuredFile = apps.get_model("django_dirt_ratings", "MeasuredFile")
    Metric = apps.get_model("django_dirt_ratings", "Metric")

    # One entry per NIfTI; the views of a file all carry the same blob, so the
    # first one seen settles it.
    per_file = {}
    rows = Image.objects.filter(raw_metrics__isnull=False).values_list(
        "step", "file1", "raw_metrics", "review_plan_id"
    )
    for step, file1, raw, review_plan_id in rows.iterator():
        per_file.setdefault((step, file1), (raw, review_plan_id))
    if not per_file:
        return

    files = [
        MeasuredFile(
            step=step,
            file1=file1,
            entities=_split(raw)[0] or None,
            review_plan_id=review_plan_id,
        )
        for (step, file1), (raw, review_plan_id) in per_file.items()
    ]
    MeasuredFile.objects.bulk_create(files, batch_size=1000)

    stored = {(f.step, f.file1): f.pk for f in MeasuredFile.objects.all()}
    metrics = [
        Metric(file_id=stored[(step, file1)], name=name, value=value)
        for (step, file1), (raw, _) in per_file.items()
        for name, value in _split(raw)[1].items()
    ]
    Metric.objects.bulk_create(metrics, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [
        ("django_dirt_ratings", "0006_measuredfile_metric"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="image",
            name="raw_metrics",
        ),
    ]
