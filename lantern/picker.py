"""Fuzzy file picker for markdown files."""

from __future__ import annotations

import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from .keys import Key, raw_mode, read_key
from .renderer import themed_panel
from .themes import Theme


_IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode", "target",
}


def find_markdown_files(root: Path, max_depth: int = 8) -> list[Path]:
    results: list[Path] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in _IGNORED_DIRS or entry.name.startswith("."):
                    continue
                walk(entry, depth + 1)
            elif entry.suffix.lower() in (".md", ".markdown"):
                results.append(entry)

    walk(root, 0)
    return sorted(results, key=lambda p: (len(p.parts), str(p).lower()))


def _fuzzy_match(query: str, text: str) -> bool:
    if not query:
        return True
    q = query.lower()
    t = text.lower()
    i = 0
    for c in t:
        if i < len(q) and c == q[i]:
            i += 1
            if i == len(q):
                return True
    return i == len(q)


def _render(
    theme: Theme,
    root: Path,
    all_files: list[Path],
    query: str,
    selected: int,
    visible_rows: int,
) -> tuple[RenderableType, list[Path], int]:
    filtered = [
        p for p in all_files
        if _fuzzy_match(query, str(p.relative_to(root)) if _is_relative(p, root) else str(p))
    ]
    if filtered:
        selected = max(0, min(selected, len(filtered) - 1))
    else:
        selected = 0

    # Window around selected
    half = visible_rows // 2
    start = max(0, selected - half)
    end = min(len(filtered), start + visible_rows)
    start = max(0, end - visible_rows)

    table = Table.grid(padding=(0, 1))
    table.add_column(width=2)
    table.add_column(ratio=1)

    for i in range(start, end):
        f = filtered[i]
        label = str(f.relative_to(root)) if _is_relative(f, root) else str(f)
        if i == selected:
            marker = Text("▶", style=theme.accent)
            row_text = Text(label, style=theme.title)
        else:
            marker = Text(" ")
            row_text = Text(label, style=theme.text)
        table.add_row(marker, row_text)

    if query:
        prompt = Text("  ", style=theme.footer)
        prompt.append("filter › ", style=theme.accent)
        prompt.append(query, style=theme.title)
        prompt.append("▏", style=theme.accent)  # faux cursor
    else:
        prompt = Text(
            "  type to filter  ·  ↑/↓ navigate  ·  Enter open  ·  Esc cancel",
            style=theme.footer,
        )

    status = Text()
    status.append(f"  {len(filtered)}", style=theme.title)
    status.append(f" / {len(all_files)} files", style=theme.footer)

    body = Group(prompt, Text(""), table, Text(""), status)

    panel = themed_panel(
        body,
        theme,
        title="Lantern — choose a file",
        subtitle=Text(str(root), style=theme.footer),
    )
    return Align.center(panel, vertical="middle"), filtered, selected


def _is_relative(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def pick_file(console: Console, theme: Theme, root: Path | None = None) -> Path | None:
    if root is None:
        root = Path.cwd()
    all_files = find_markdown_files(root)
    if not all_files:
        console.print(f"[red]No markdown files found under {root}[/]")
        return None

    query = ""
    selected = 0
    visible_rows = max(8, console.size[1] - 12)

    rendered, filtered, selected = _render(theme, root, all_files, query, selected, visible_rows)

    with raw_mode():
        with Live(rendered, console=console, screen=True, auto_refresh=False) as live:
            live.update(rendered, refresh=True)
            while True:
                key = read_key()

                if key in (Key.CTRL_C, Key.ESC):
                    return None
                if key == Key.ENTER:
                    if filtered:
                        return filtered[selected]
                    continue
                if key == Key.UP:
                    selected = max(0, selected - 1)
                elif key == Key.DOWN:
                    selected = min(max(0, len(filtered) - 1), selected + 1)
                elif key == Key.PAGE_UP:
                    selected = max(0, selected - visible_rows)
                elif key == Key.PAGE_DOWN:
                    selected = min(max(0, len(filtered) - 1), selected + visible_rows)
                elif key == Key.HOME:
                    selected = 0
                elif key == Key.END:
                    selected = max(0, len(filtered) - 1)
                elif key == Key.BACKSPACE:
                    query = query[:-1]
                    selected = 0
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    query += key
                    selected = 0

                rendered, filtered, selected = _render(
                    theme, root, all_files, query, selected, visible_rows
                )
                live.update(rendered, refresh=True)


def parse_dragged_path(raw: str) -> Path | None:
    """Parse a path that a terminal wrote to stdin from a drag-and-drop.

    Handles: backslash-escaped spaces (Terminal.app default), single/double
    quoted paths (iTerm2 option), ``file://`` URIs, and leading/trailing
    whitespace. If multiple paths were dropped, returns the first one.
    """
    s = raw.strip()
    if not s:
        return None

    if s.startswith(("file://", "'file://", '"file://')):
        # A single file:// URI encodes its own spaces as %20, so shlex would
        # mangle it. Strip surrounding quotes, then take the first token.
        s = s.strip("'\"")
        first = s.split()[0]
        parsed = urlparse(first)
        return Path(unquote(parsed.path)).expanduser()

    try:
        tokens = shlex.split(s)
    except ValueError:
        # Unbalanced quote etc. — fall back to the raw string.
        tokens = [s]
    if not tokens:
        return None
    return Path(tokens[0]).expanduser()


def prompt_drag(console: Console, theme: Theme) -> Path | None:
    """Show a prompt asking the user to drag a file into the terminal."""
    panel = themed_panel(
        Group(
            Text("将 markdown 文件拖拽到此处，然后按 Enter", style=theme.title),
            Text(""),
            Text(
                "直接回车打开 fuzzy picker  ·  Ctrl-C 取消",
                style=theme.footer,
            ),
        ),
        theme,
    )
    console.print(panel)

    try:
        raw = input("› ")
    except (EOFError, KeyboardInterrupt):
        return None

    if not raw.strip():
        return pick_file(console, theme)

    path = parse_dragged_path(raw)
    if path is None:
        console.print("[red]Could not parse path from input.[/]")
        return None
    return path
