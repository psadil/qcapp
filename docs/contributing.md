# Contributing

## Development environment

The project uses [pixi](https://pixi.sh). The `dev` environment has the app plus test and
lint tooling:

```shell
pixi install -e dev
pixi run -e dev test        # pytest (models, services, selectors, views, api, frontend)
```

The frontend tests drive a real browser with Playwright; the first run installs the browser
binaries.

## Tests

Tests live under `tests/`, grouped by layer (`models/`, `services/`, `selectors/`,
`views/`, `apis/`, `frontend/`). Shared fixtures are in `tests/conftest.py`, which uses a
file-based SQLite test database so the live-server thread and the test thread share rows.

## Linting

Formatting and linting run through [prek](https://github.com/j178/prek) (see `prek.toml`)
with ruff and codespell.

## Documentation

The docs are built with [Zensical](https://zensical.org). Work on them in the `docs`
environment:

```shell
pixi run -e docs docs-serve     # live-reload preview
pixi run -e docs docs-build     # one-off build (also the CI gate)
```

`docs-serve`/`docs-build` first regenerate the API-reference pages (`docs-gen`): an
`ast`-based script (`tools/gen_reference.py`) writes the `docs/reference/` module pages, and
`manage export_openapi` writes the REST-API page from the live django-ninja schema. Those
generated pages are not checked in — do not edit them by hand; edit the source or the
generator.

## Branches and pull requests

Work on a feature branch and open a pull request against `main`.
