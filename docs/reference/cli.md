# Command line

Image generation is a single management command, run in the `manage` pixi environment (the
neuroimaging stack). Build a catalog with `bidslake index` first, then:

```shell
pixi run -e manage manage render study.duckdb
```

Run `manage render --help` for the full, always-current option list. In brief:

| Option | Effect |
| --- | --- |
| `--step <name>` | Render only the named step(s); repeatable. Default: every step present. |
| `--update` | Re-render images already in the database (preserves ratings). |
| `--sub` / `--res` | Filter to a subject label or resolution entity. |
| `--workers <n>` | Number of render worker processes (default: CPU count). |

## Review ordering

A dataset's [review plan](../concepts/review-ordering.md) (a `dirt.toml` file) chooses the
ordering strategy and the metric each step is ordered by. It is applied and (re)computed
with two web-safe commands:

```shell
manage plan dirt.toml     # validate, persist, and activate a review plan (--show to print the active one)
manage prioritize         # recompute Image.priority from measured metrics per the active plan
```

`render` measures every file it renders — [every metric DIRT can compute](../concepts/metrics.md)
from that file's inputs, whether or not anything orders by it — and stamps each image with the
active plan; `manage prioritize` z-scores the metric a step names into the ordering key. With no
active plan the metrics are still computed and stored, and ordering is the default
breadth-first. The `dirt.toml` format has a
[JSON Schema](https://psadil.github.io/dirt/api/plan.schema.json) for editor completion and
validation, regenerated at every docs build by `manage export_plan_schema`.

## Adding a step

A processing step is one declarative `StepSpec` under
`django_dirt_ratings/management/ingest/specs/` — a `discover` callable that queries the
bidslake catalog for its files and returns `RenderJob`s. No new command is needed.

::: django_dirt_ratings.management.ingest.registry
    options:
      members:
        - StepSpec
        - RenderJob
