#!/usr/bin/env python
"""Generate the Markdown API-reference pages under ``docs/reference/``.

Pure ``ast`` — this script imports **nothing** from the project (no Django, no
neuro stack), so it runs in the lightweight ``docs`` pixi environment and never
needs a settings bootstrap. It reads the source files directly and emits one
Markdown page per module from public signatures + docstrings.

This is the engine-agnostic replacement for ``mkdocs-gen-files`` +
``mkdocstrings`` (which Zensical does not yet run as MkDocs plugins). Run it via
``pixi run -e docs docs-gen`` (chained ahead of the Zensical build); the
``reference/`` pages it writes are generated artifacts, not hand-maintained.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "django_dirt_ratings"
OUT = REPO / "docs" / "reference"
REPO_URL = "https://github.com/psadil/dirt"

# (source module, output page, human title) for the plain-module pages.
MODULES = [
    ("services.py", "services.md", "Services (write side)"),
    ("selectors.py", "selectors.md", "Selectors (read side)"),
    ("models.py", "models.md", "Models"),
]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a function's signature using ``ast.unparse`` on its args."""
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({args}){returns}"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _doc(node: ast.AST) -> str:
    return (ast.get_docstring(node) or "").strip()


def _render_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    lines = [f"### `{node.name}`", "", "```python", _signature(node), "```", ""]
    doc = _doc(node)
    if doc:
        lines += [doc, ""]
    return lines


def _render_class(node: ast.ClassDef) -> list[str]:
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    header = f"### `{node.name}`" + (f" (`{bases}`)" if bases else "")
    lines = [header, ""]
    doc = _doc(node)
    if doc:
        lines += [doc, ""]
    methods = [
        n
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(n.name)
    ]
    for method in methods:
        lines += [
            f"- `{method.name}(...)`"
            + (f" — {_doc(method).splitlines()[0]}" if _doc(method) else ""),
        ]
    if methods:
        lines.append("")
    return lines


def render_module(src: Path, title: str) -> str:
    tree = ast.parse(src.read_text(), filename=str(src))
    rel = src.relative_to(REPO)
    lines = [
        f"# {title}",
        "",
        f"*Auto-generated from [`{rel}`]({REPO_URL}/blob/main/{rel}) — do not edit by hand.*",
        "",
    ]
    module_doc = _doc(tree)
    if module_doc:
        lines += [module_doc, ""]

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            lines += _render_class(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(
            node.name
        ):
            lines += _render_function(node)
    return "\n".join(lines).rstrip() + "\n"


def render_cli() -> str:
    """Document the management commands from their handle() docstrings + signatures."""
    cmd_dir = SRC / "management" / "commands"
    lines = [
        "# Command line",
        "",
        "*Auto-generated from the management-command modules — do not edit by hand.*",
        "",
        "Image generation runs as Django management commands in the `manage` pixi",
        "environment (the heavy neuroimaging stack). Run any command with `--help`",
        "for its full options.",
        "",
    ]
    for src in sorted(cmd_dir.glob("*.py")):
        if src.name.startswith("_"):
            continue
        tree = ast.parse(src.read_text(), filename=str(src))
        command = next(
            (
                n
                for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "Command"
            ),
            None,
        )
        if command is None:
            continue
        handle = next(
            (
                n
                for n in command.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "handle"
            ),
            None,
        )
        summary = _doc(handle) or _doc(command) or ""
        lines += [f"## `manage {src.stem}`", ""]
        if summary:
            lines += [summary, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_index() -> str:
    return (
        "# Reference\n\n"
        "Auto-generated API reference. These pages are produced by "
        "`pixi run -e docs docs-gen` and should not be edited by hand.\n\n"
        "- [Services (write side)](services.md) — the only layer that writes to the database.\n"
        "- [Selectors (read side)](selectors.md) — read-side data access.\n"
        "- [Models](models.md) — the database schema.\n"
        "- [Command line](cli.md) — image-generation management commands.\n"
        "- [REST API](api.md) — the django-ninja HTTP API (generated by `manage export_openapi`).\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for module, page, title in MODULES:
        (OUT / page).write_text(render_module(SRC / module, title))
    (OUT / "cli.md").write_text(render_cli())
    (OUT / "index.md").write_text(render_index())
    print(f"Wrote reference pages to {OUT.relative_to(REPO)}/")


if __name__ == "__main__":
    main()
