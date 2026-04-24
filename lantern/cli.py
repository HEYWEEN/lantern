"""CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console

from .picker import pick_file, prompt_drag
from .presenter import Presenter
from .themes import all_theme_names, get_theme

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Lantern — render a markdown file as a slideshow in your terminal.",
)


@app.command()
def main(
    file: Path | None = typer.Argument(None, help="Path to a markdown file. If omitted, a drag-and-drop prompt is shown."),
    theme: str = typer.Option("light", "--theme", "-t", help=f"Theme: {', '.join(all_theme_names())}"),
    pick: bool = typer.Option(False, "--pick", "-p", help="Open the fuzzy file picker instead of the drag-and-drop prompt."),
) -> None:
    if theme not in all_theme_names():
        typer.echo(f"Unknown theme: {theme}. Options: {', '.join(all_theme_names())}", err=True)
        raise typer.Exit(code=2)

    if file is None:
        console = Console()
        t = get_theme(theme)
        chosen = pick_file(console, t) if pick else prompt_drag(console, t)
        if chosen is None:
            typer.echo("No file selected.", err=True)
            raise typer.Exit(code=1)
        file = chosen

    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(code=1)
    if not file.is_file():
        typer.echo(f"Not a file: {file}", err=True)
        raise typer.Exit(code=1)

    try:
        Presenter(file, theme_name=theme).run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    app()
