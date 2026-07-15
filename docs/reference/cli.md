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

## Adding a step

A processing step is one declarative `StepSpec` under
`django_dirt_ratings/management/ingest/specs/` — a `discover` callable that queries the
bidslake catalog for its files and returns `RenderJob`s. No new command is needed.

::: django_dirt_ratings.management.ingest.registry
    options:
      members:
        - StepSpec
        - RenderJob
