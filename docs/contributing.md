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

The module reference pages (`docs/reference/`) render from source docstrings via
[mkdocstrings](https://zensical.org/docs/setup/extensions/mkdocstrings) (`::: module`
directives) — edit the docstrings, not the pages. The REST-API page and OpenAPI schema are
generated from the live django-ninja API by `manage export_openapi`, which `docs-serve` /
`docs-build` run first (via `docs-gen`); those two files are not checked in.

## Branches and pull requests

Work on a feature branch and open a pull request against `main`.
