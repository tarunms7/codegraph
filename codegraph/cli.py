"""CLI for codegraph — expose CodeGraph functionality via command line."""

from __future__ import annotations

import json
import shutil

import click

from codegraph import CodeGraph, __version__
from codegraph.exceptions import CodeGraphError


@click.group()
@click.version_option(version=__version__, prog_name="codegraph")
def main() -> None:
    """codegraph — Ranked, token-budget-aware code context for LLMs and AI agents."""


@main.command()
@click.argument("repo_path")
@click.option("--budget", default=2048, type=int, help="Token budget (default 2048).")
@click.option(
    "--format",
    "fmt",
    default="markdown",
    type=click.Choice(["markdown", "json"]),
    help="Output format.",
)
def map(repo_path: str, budget: int, fmt: str) -> None:
    """Generate a global repo map ranked by structural importance."""
    try:
        cg = CodeGraph(repo_path)
        result = cg.repo_map(token_budget=budget, format=fmt)  # type: ignore[arg-type]
        click.echo(result)
    except CodeGraphError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("repo_path")
@click.argument("files", nargs=-1, required=True)
@click.option("--budget", default=4096, type=int, help="Token budget (default 4096).")
@click.option(
    "--format",
    "fmt",
    default="markdown",
    type=click.Choice(["markdown", "json"]),
    help="Output format.",
)
def context(repo_path: str, files: tuple[str, ...], budget: int, fmt: str) -> None:
    """Get ranked context relevant to specific files."""
    try:
        cg = CodeGraph(repo_path)
        result = cg.context_for(list(files), token_budget=budget, format=fmt)  # type: ignore[arg-type]
        click.echo(result)
    except CodeGraphError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("repo_path")
@click.argument("text")
@click.option("--budget", default=4096, type=int, help="Token budget (default 4096).")
@click.option(
    "--format",
    "fmt",
    default="markdown",
    type=click.Choice(["markdown", "json"]),
    help="Output format.",
)
def query(repo_path: str, text: str, budget: int, fmt: str) -> None:
    """Get ranked context relevant to a natural language query."""
    try:
        cg = CodeGraph(repo_path)
        result = cg.query(text, token_budget=budget, format=fmt)  # type: ignore[arg-type]
        click.echo(result)
    except CodeGraphError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("repo_path")
@click.option("--text", help="Natural-language retrieval query.")
@click.option(
    "--file",
    "files",
    multiple=True,
    help="Seed file path. Repeat to provide multiple files.",
)
@click.option("--limit", default=8, type=int, help="Maximum files to return.")
@click.option("--symbols", "symbol_limit", default=5, type=int, help="Symbols per file.")
@click.option(
    "--neighbors",
    "neighbor_limit",
    default=3,
    type=int,
    help="Connected neighbor files per result.",
)
def evidence(
    repo_path: str,
    text: str | None,
    files: tuple[str, ...],
    limit: int,
    symbol_limit: int,
    neighbor_limit: int,
) -> None:
    """Return structured evidence for a query or seed files."""
    try:
        if bool(text) == bool(files):
            raise click.ClickException("Provide either --text or one or more --file values.")

        cg = CodeGraph(repo_path)
        if text:
            result = cg.evidence_for_query(
                text,
                limit=limit,
                symbol_limit=symbol_limit,
                neighbor_limit=neighbor_limit,
            )
        else:
            result = cg.evidence_for_files(
                list(files),
                limit=limit,
                symbol_limit=symbol_limit,
                neighbor_limit=neighbor_limit,
            )
        click.echo(json.dumps(result.to_dict(), indent=2))
    except CodeGraphError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("repo_path")
def stats(repo_path: str) -> None:
    """Show index statistics for a repository."""
    try:
        cg = CodeGraph(repo_path)
        s = cg.stats
        click.echo(f"Files:        {s['files']}")
        click.echo(f"Symbols:      {s['symbols']}")
        click.echo(f"Edges:        {s['edges']}")
        click.echo(f"Languages:    {s['languages']}")
        click.echo(f"Cache hits:   {s['cache_hits']}")
        click.echo(f"Cache misses: {s['cache_misses']}")
        click.echo(f"Index time:   {s['index_time_ms']:.1f}ms")
    except CodeGraphError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("repo_path")
def clear(repo_path: str) -> None:
    """Clear the .codegraph cache directory."""
    import os
    from pathlib import Path

    cache_dir = os.path.join(str(Path(repo_path).resolve()), ".codegraph")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        click.echo(f"Cleared cache: {cache_dir}")
    else:
        click.echo("No cache directory found.")
