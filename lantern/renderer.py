"""Render a Slide into a rich Renderable (Panel with centered body + footer)."""

from __future__ import annotations

import re
from pathlib import Path

from rich import box
from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.control import ControlType
from rich.markdown import BlockQuote, Markdown, TableElement
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Table
from rich.text import Text

from .images import (
    detect_protocol,
    render_image,
    render_iterm2_image,
    resolve_image_source,
)
from .parser import Slide
from .themes import Theme


_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Dummy control marker used on segments that carry raw terminal escapes
# (iTerm2 OSC 1337). Rich treats a Segment with any truthy ``control`` value
# as zero-width for layout while still writing its ``text`` verbatim to the
# terminal (see rich.console.Console._render_buffer) — exactly what we need
# for sneaking an image escape past Rich's cell-length accounting.
_ZERO_WIDTH_CONTROL = ((ControlType.CURSOR_MOVE_TO_COLUMN, 0),)


class _ITerm2Image:
    """A rectangular image drawn via iTerm2's inline-image protocol.

    Order matters: we emit ``h`` rows of ``w`` blank cells *first*, then on
    the last row we emit a single zero-width control segment that moves the
    cursor back to the rectangle's top-left, drops the OSC 1337 payload, and
    restores the cursor. Drawing the image last is what keeps it visible —
    iTerm2 replaces whichever cells the OSC covers, so any subsequent plain
    text (e.g. padding spaces) written to those cells would otherwise erase
    the image. Nothing is written to the rectangle after the OSC fires.
    """

    def __init__(self, osc: str, width: int, height: int) -> None:
        self.osc = osc
        self.width = width
        self.height = height

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        w = max(1, min(self.width, options.max_width))
        h = max(1, self.height)
        blank = Segment(" " * w)
        for row in range(h):
            yield blank
            if row < h - 1:
                yield Segment.line()

        # Cursor is now at the end of the last blank row, i.e. ``w`` cells
        # to the right of the rectangle's left edge, ``h-1`` rows below its
        # top edge. Jump back to the top-left, draw, then restore so the
        # surrounding layout sees zero net cursor movement.
        up = f"\x1b[{h - 1}A" if h > 1 else ""
        back = f"\x1b[{w}D"
        draw = f"\x1b7{up}{back}{self.osc}\x1b8"
        yield Segment(draw, control=_ZERO_WIDTH_CONTROL)
        # Terminate the last row so a following renderable (e.g. the image
        # caption) starts on its own line. Without this, Rich's
        # split_and_crop_lines merges the caption's segments into the image's
        # last row, so the caption gets written right after the image on the
        # same terminal row and the panel crops it.
        yield Segment.line()


class _FoldTableElement(TableElement):
    """Same as rich's built-in table element, but columns fold instead of truncating.

    ``rich.table.Column`` defaults ``overflow="ellipsis"``, so narrow Chinese cells
    get cropped with ``…``. Passing ``overflow="fold"`` makes cells wrap to the
    next line instead — which is what slide tables want.
    """

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        table = Table(
            box=box.SIMPLE,
            pad_edge=False,
            style="markdown.table.border",
            show_edge=True,
            collapse_padding=True,
        )
        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                heading = column.content.copy()
                heading.stylize("markdown.table.header")
                table.add_column(heading, overflow="fold", no_wrap=False)
        if self.body is not None:
            for row in self.body.rows:
                table.add_row(*(element.content for element in row.cells))
        yield table


class _SlideBlockQuote(BlockQuote):
    """BlockQuote that paints the ▌ bar separately from the quote body.

    Rich's default uses one ``markdown.block_quote`` style for both, which
    forces the border to match the (usually muted) body color. Reading the
    border from ``markdown.block_quote.border`` lets the theme pick e.g. a
    soft blue bar next to professional-gray text.
    """

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        render_options = options.update(width=options.max_width - 4)
        body_style = self.style
        border_style = console.get_style(
            "markdown.block_quote.border", default=body_style
        )
        lines = console.render_lines(self.elements, render_options, style=body_style)
        new_line = Segment("\n")
        padding = Segment("▌ ", border_style)
        for line in lines:
            yield padding
            yield from line
            yield new_line


class _SlideMarkdown(Markdown):
    """Markdown with table cells that wrap and blockquotes with split colors."""

    elements = {
        **Markdown.elements,
        "table_open": _FoldTableElement,
        "block_quote_open": _SlideBlockQuote,
    }


def _body_from_markdown(md_source: str, theme: Theme) -> RenderableType:
    return _SlideMarkdown(md_source, code_theme=theme.code_theme)


def themed_panel(
    body: RenderableType,
    theme: Theme,
    *,
    title: str = "Lantern",
    subtitle: RenderableType | None = None,
    padding: tuple[int, int] = (1, 2),
    width: int | None = None,
    height: int | None = None,
) -> Panel:
    """Build a Panel with the theme's border, bg, and accent title applied."""
    return Panel(
        body,
        box=ROUNDED,
        style=theme.panel_style(),
        border_style=theme.border,
        title=Text(title, style=theme.accent),
        subtitle=subtitle,
        padding=padding,
        width=width,
        height=height,
    )


_IMAGE_V_PAD = 1  # blank lines reserved above + below each image


def _image_block(
    alt: str, img_src: str, base_dir: Path, max_w: int, max_h: int, theme: Theme
) -> RenderableType:
    """Render an inline markdown image — local path or http(s) URL.

    Alt text is deliberately dropped from successful renders: we only surface
    it when the image itself is unavailable, as part of the error placeholder.

    Vertical breathing room: the returned block includes a blank line above
    and below the image so it doesn't run flush against surrounding copy.
    The image's own height is shrunk by the same amount so the total slot
    matches the ``max_h`` the caller budgeted — otherwise two images on the
    same slide would push the footer out of view.
    """
    local = resolve_image_source(img_src, base_dir)
    if local is None:
        # Remote fetch failed / local file missing. Show a compact placeholder
        # instead of a stack trace so the rest of the slide still renders.
        placeholder = Text(
            f"[image unavailable: {alt or img_src}]",
            style=theme.footer,
            justify="center",
        )
        return Align.center(placeholder)

    inner_h = max(4, max_h - 2 * _IMAGE_V_PAD)
    pad = Text("")

    if detect_protocol() == "iterm2":
        iterm = render_iterm2_image(local, max_w_cells=max_w, max_h_cells=inner_h)
        if iterm is not None:
            osc, w_cells, h_cells = iterm
            return Group(pad, Align.center(_ITerm2Image(osc, w_cells, h_cells)), pad)
        # Fall through to ASCII if iTerm2 payload build failed.

    ansi, _, _ = render_image(local, max_w_cells=max_w, max_h_cells=inner_h)
    img = Text.from_ansi(ansi, no_wrap=True, overflow="crop")
    return Group(pad, Align.center(img), pad)


def _split_body(body: str) -> list[tuple[str, ...]]:
    """Return a list of ("md", text) / ("img", alt, path) chunks in order."""
    chunks: list[tuple[str, ...]] = []
    last = 0
    for m in _IMG_RE.finditer(body):
        line_start = body.rfind("\n", 0, m.start()) + 1
        line = body[line_start:body.find("\n", m.end()) if body.find("\n", m.end()) != -1 else len(body)]
        if line.lstrip().startswith("    ") or line.lstrip().startswith("\t"):
            continue  # indented code block
        pre = body[last:m.start()]
        if pre.strip():
            chunks.append(("md", pre))
        chunks.append(("img", m.group(1), m.group(2)))
        last = m.end()
    tail = body[last:]
    if tail.strip():
        chunks.append(("md", tail))
    if not chunks:
        chunks.append(("md", body))
    return chunks


def _build_markdown_block(
    body_text: str, theme: Theme, base_dir: Path, body_w: int, body_h: int
) -> RenderableType:
    chunks = _split_body(body_text)
    img_count = sum(1 for c in chunks if c[0] == "img")
    # Give each image most of the viewport so screenshots / diagrams are
    # actually legible. The slide scrolls when text + image stacks taller
    # than body_h, which is fine — users can page through.
    per_image_h = max(6, (body_h - 2) // max(1, img_count)) if img_count else 0

    renderables: list[RenderableType] = []
    for ch in chunks:
        if ch[0] == "md":
            renderables.append(_body_from_markdown(ch[1].strip("\n"), theme))
        else:
            _, alt, path = ch
            renderables.append(
                _image_block(
                    alt, path, base_dir, max_w=body_w - 2, max_h=per_image_h, theme=theme
                )
            )
    return Group(*renderables)


def _build_body(
    slide: Slide, theme: Theme, base_dir: Path, body_w: int, body_h: int
) -> RenderableType:
    """Raw body renderable for a non-title slide (pre-scroll, pre-clip).

    Deliberately NOT wrapped in an Align-with-fixed-height: we want to know
    the slide's natural line count so the presenter can decide whether
    scrolling is needed.
    """
    if slide.kind == "section":
        title = Text(slide.title or "", style=theme.title, justify="center")
        spacer = Text("")
        md = _build_markdown_block(slide.body, theme, base_dir, body_w, max(1, body_h - 2))
        return Group(title, spacer, md)
    # plain "body" — no heading
    return _build_markdown_block(slide.body, theme, base_dir, body_w, body_h)


class _Viewport:
    """A fixed-height slice of a renderable's rendered lines.

    The inner renderable is rendered to a full list of segment-lines at the
    configured width, then sliced to `[offset : offset + height]`. Used to
    scroll long slides inside the panel without touching the border.
    """

    def __init__(
        self,
        inner: RenderableType,
        width: int,
        height: int,
        offset: int,
    ) -> None:
        self.inner = inner
        self.width = width
        self.height = height
        self.offset = offset

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        opts = options.update(width=self.width, height=None)
        lines = console.render_lines(self.inner, opts, pad=True)
        # No upper clamp: a paged last slide ends at `offset + height` even
        # when that's past the content — blank rows are padded below. This
        # makes pages truly disjoint (page N has no overlap with page N-1)
        # instead of "sliding window" scrolling that repeats the tail of the
        # previous page to fill the viewport.
        start = max(0, self.offset)
        end = start + self.height
        visible = lines[start:end]
        # Pad short / past-the-end slides so the viewport always emits exactly
        # `height` rows — keeps the panel interior rectangular regardless of
        # content length or scroll position.
        blank = Segment(" " * self.width)
        while len(visible) < self.height:
            visible.append([blank])
        for i, line in enumerate(visible):
            yield from line
            if i < len(visible) - 1:
                yield Segment("\n")


def measure_body_lines(
    inner: RenderableType, console: Console, body_w: int
) -> int:
    """How many rendered terminal rows the body would take at `body_w` width."""
    opts = console.options.update(width=body_w, height=None)
    return len(console.render_lines(inner, opts, pad=False))


def _footer(
    file_name: str,
    page: int,
    total: int,
    theme: Theme,
    bar_width: int = 24,
    scroll_hint: Text | None = None,
) -> Text:
    ratio = page / total if total > 0 else 0.0
    filled = max(0, min(bar_width, round(ratio * bar_width)))
    empty = bar_width - filled
    t = Text()
    t.append(f" {file_name} ", style=theme.footer)
    t.append("·", style=theme.footer)
    t.append(f" {page}/{total} ", style=theme.footer)
    if scroll_hint is not None:
        t.append("·", style=theme.footer)
        t.append(" ", style=theme.footer)
        t.append_text(scroll_hint)
        t.append(" ", style=theme.footer)
    t.append("·", style=theme.footer)
    t.append(" ", style=theme.footer)
    fill_ch, empty_ch = theme.progress_chars
    t.append(fill_ch * filled, style=theme.progress_filled)
    t.append(empty_ch * empty, style=theme.progress_empty)
    t.append(" ", style=theme.footer)
    return t


def _scroll_hint(offset: int, max_scroll: int, body_h: int, theme: Theme) -> Text:
    """Compact indicator like '↑ 2/3 ↓' showing scroll position on long slides.

    Arrows dim when you can't scroll further in that direction. The page math
    has to handle the case where max_scroll < body_h (overflow of just a few
    lines): naive offset//body_h would always round down to 0 and the page
    counter would never move. ceil(offset / body_h) fixes that.
    """
    step = max(1, body_h)
    total_pages = 1 + (max_scroll + step - 1) // step
    if offset <= 0:
        cur_page = 1
    elif offset >= max_scroll:
        cur_page = total_pages
    else:
        cur_page = 1 + (offset + step - 1) // step
    cur_page = min(total_pages, max(1, cur_page))
    up_style = theme.accent if offset > 0 else theme.progress_empty
    down_style = theme.accent if offset < max_scroll else theme.progress_empty
    t = Text()
    t.append("↑", style=up_style)
    t.append(f" {cur_page}/{total_pages} ", style=theme.footer)
    t.append("↓", style=down_style)
    return t


def body_viewport_height(total_height: int) -> int:
    """How many rows of slide body are actually visible in the panel.

    Kept in sync with render_slide's inner_h/body_h math so the presenter can
    use 'one viewport' as its scroll step without reaching into the renderer.
    """
    inner_h = max(6, total_height - 4)
    return max(1, inner_h - 2)


def render_slide(
    slide: Slide,
    theme: Theme,
    base_dir: Path,
    width: int,
    height: int,
    file_name: str,
    page: int,
    total: int,
    scroll: int = 0,
    console: Console | None = None,
) -> tuple[RenderableType, int]:
    """Render one slide.

    Returns (renderable, max_scroll). `max_scroll` is the largest valid value
    of `scroll` for the current slide+viewport (0 when the content fits).
    """
    panel_w = min(width, 110)
    inner_h = max(6, height - 4)
    body_w = panel_w - 6
    body_h = inner_h - 2

    if slide.kind == "title":
        title = Text(slide.title or "", style=theme.title, justify="center")
        content: RenderableType = Align.center(title, vertical="middle", height=body_h)
        max_scroll = 0
        scroll_hint: Text | None = None
    else:
        body = _build_body(slide, theme, base_dir, body_w, body_h)
        if console is None:
            # Fallback: best-effort with a temp console. Should rarely happen
            # because the presenter always passes its live Console in.
            console = Console(width=body_w, record=False)
        total_lines = measure_body_lines(body, console, body_w)
        # Page-aligned scrolling: each ↓/↑ step advances by body_h rows and
        # max_scroll snaps up to the nearest whole page, so the last page
        # shows only the leftover content (padded below with blanks) instead
        # of backing up to overlap with the previous page.
        if total_lines > body_h:
            pages = (total_lines + body_h - 1) // body_h
            max_scroll = (pages - 1) * body_h
        else:
            max_scroll = 0
        scroll = max(0, min(scroll, max_scroll))
        if max_scroll == 0:
            content = Align(body, align="left", vertical="top", height=body_h)
            scroll_hint = None
        else:
            content = _Viewport(body, width=body_w, height=body_h, offset=scroll)
            scroll_hint = _scroll_hint(scroll, max_scroll, body_h, theme)

    panel = themed_panel(
        content,
        theme,
        subtitle=_footer(file_name, page, total, theme, scroll_hint=scroll_hint),
        width=panel_w,
        height=height - 1,
    )
    renderable: RenderableType = panel if panel_w >= width else Align.center(panel)
    return renderable, max_scroll


def render_toc(
    entries: list[tuple[int, str, int]],
    selection: int,
    theme: Theme,
    width: int,
    height: int,
    file_name: str,
    page: int,
    total: int,
) -> RenderableType:
    """Render the contents page as a two-level tree.

    ``entries`` is a list of ``(slide_index_0based, title, depth)`` triples,
    where ``depth`` is 0 for roots (H1-level titles) and 1 for children
    (sections nested under the most recent title). ``selection`` is the
    index into ``entries`` currently highlighted. The list scrolls
    automatically so the highlighted row stays on screen; ↑/↓ move the
    selection and the view follows.
    """
    panel_w = min(width, 110)
    inner_h = max(6, height - 4)
    body_w = panel_w - 6
    body_h = inner_h - 2

    heading = Text("目录 · Contents", style=theme.title, justify="center")
    hint = Text(
        "↑↓ 选择   Enter 跳转   c 回到目录",
        style=theme.footer,
        justify="center",
    )
    # Body area we actually have for the list: subtract heading + blank + hint.
    list_h = max(1, body_h - 3)

    if not entries:
        empty = Text("(没有可跳转的标题)", style=theme.footer, justify="center")
        body: RenderableType = Group(heading, Text(""), empty)
        panel = themed_panel(
            body,
            theme,
            subtitle=_footer(file_name, page, total, theme),
            width=panel_w,
            height=height - 1,
        )
        return panel if panel_w >= width else Align.center(panel)

    # Keep the highlighted row in view. Selection near the top → start at 0;
    # near the bottom → clamp; otherwise center-ish.
    if len(entries) <= list_h:
        offset = 0
    else:
        offset = max(0, min(len(entries) - list_h, selection - list_h // 2))

    # Pre-compute which child is the last one under each parent so we can
    # use ``└─`` there instead of ``├─``. "Last" = next entry is either a
    # root (depth 0) or past the end of the list.
    is_last_child = [False] * len(entries)
    for i, (_idx, _title, depth) in enumerate(entries):
        if depth == 0:
            continue
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        if nxt is None or nxt[2] == 0:
            is_last_child[i] = True

    rows: list[Text] = []
    for vis_i, (_slide_idx, title, depth) in enumerate(entries[offset : offset + list_h]):
        real_i = vis_i + offset
        is_sel = real_i == selection
        row = Text()
        # Selection marker (same width for every row, so columns line up).
        row.append("▸ " if is_sel else "  ", style=theme.accent if is_sel else theme.text)
        # Tree connector for depth-1 rows.
        if depth >= 1:
            connector = "└─ " if is_last_child[real_i] else "├─ "
            row.append(connector, style=theme.footer)
        # Roots get the title style (bold); children get the default text
        # style so the hierarchy reads at a glance. Selection overrides both.
        if is_sel:
            title_style = theme.accent
        else:
            title_style = theme.title if depth == 0 else theme.text
        row.append(title, style=title_style)
        rows.append(row)

    # Left-align each row within the block (numbers stay stacked per depth),
    # then wrap the block in Align.center so the tree column as a whole sits
    # in the middle of the panel.
    rows_block: RenderableType = Align.center(Group(*rows))
    body = Group(heading, Text(""), rows_block, Text(""), hint)
    panel = themed_panel(
        body,
        theme,
        subtitle=_footer(file_name, page, total, theme),
        width=panel_w,
        height=height - 1,
    )
    return panel if panel_w >= width else Align.center(panel)


def render_help(theme: Theme, width: int, height: int) -> RenderableType:
    rows = [
        ("→  Space  Enter  l  n",    "Next slide"),
        ("←  Backspace  h  p",       "Previous slide"),
        ("↓  j  PgDn",               "Scroll one page (long slide) / next"),
        ("↑  k  PgUp",               "Scroll one page (long slide) / prev"),
        ("g  Home",                  "First slide (contents)"),
        ("G  End",                   "Last slide"),
        ("c",                        "Jump to contents page"),
        ("<N> Enter",                "Jump to slide N"),
        ("o",                        "Open a different file"),
        ("r",                        "Reload current file"),
        ("t",                        "Cycle theme (dark / light / mono)"),
        ("?",                        "Toggle this help"),
        ("q  Esc  Ctrl-C",           "Quit"),
    ]
    t = Text()
    t.append("Keyboard shortcuts\n\n", style=theme.accent)
    key_w = max(len(k) for k, _ in rows)
    for key, desc in rows:
        t.append(f"  {key.ljust(key_w)}  ", style=theme.title)
        t.append(desc + "\n", style=theme.text)
    t.append("\n(press any key to close)", style=theme.footer)

    panel_w = min(width, max(60, min(width, 80)))
    return Align.center(
        themed_panel(
            Align(t, vertical="middle"),
            theme,
            title="Help",
            padding=(1, 3),
            width=panel_w,
            height=min(height - 2, len(rows) + 8),
        )
    )
