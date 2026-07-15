# Reference

API reference for the `django_dirt_ratings` app.

- [Services](services.md) — the write side; the only layer that creates or updates rows.
- [Selectors](selectors.md) — the read side; queries and the review-ordering lookup.
- [Models](models.md) — the database schema.
- [Command line](cli.md) — the `render` image-generation command.
- [REST API](api.md) — the django-ninja HTTP API (generated from the live schema).

The module pages below are rendered with
[mkdocstrings](https://zensical.org/docs/setup/extensions/mkdocstrings) from the source
docstrings — griffe reads the source statically, so nothing here needs a running app.
