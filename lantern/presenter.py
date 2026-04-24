"""Main slideshow loop: render current slide, dispatch keyboard events."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .keys import Key, raw_mode, read_key
from .parser import Slide, parse_slides
from .picker import pick_file
from .renderer import body_viewport_height, render_help, render_slide, render_toc
from .themes import get_theme, next_theme


class Presenter:
    def __init__(self, file_path: Path, theme_name: str = "dark") -> None:
        self.file_path = file_path
        self.theme_name = theme_name
        self.console = Console(force_terminal=True)
        self.slides: list[Slide] = []
        # TOC entries: (slide_index_into_self.slides, title, depth). Depth 0
        # = H1-level (title slide), depth 1 = H2-level (section) nested under
        # the most recent title. Only populated when the deck has at least
        # one heading worth listing.
        self.toc_entries: list[tuple[int, str, int]] = []
        self.toc_selection = 0
        self.index = 0
        self.number_buffer = ""
        self.show_help = False
        # Scroll state for the current slide. Reset on any slide change.
        self.scroll = 0
        self.max_scroll = 0
        self.reload()

    # --- state ---

    def reload(self) -> None:
        text = self.file_path.read_text(encoding="utf-8")
        parsed = parse_slides(text)
        if not parsed:
            parsed = [Slide(title=None, body="(empty file)", kind="body", index=0)]

        # Walk slides in order and build a two-level tree: title slides are
        # roots (depth 0); sections that follow are nested under the most
        # recent title (depth 1). A section that precedes any title stays at
        # depth 0 on its own. Untitled body slides don't appear in the tree.
        entries: list[tuple[int, str, int]] = []
        has_title_root = False
        for i, s in enumerate(parsed):
            if not s.title:
                continue
            if s.kind == "title":
                entries.append((i, s.title, 0))
                has_title_root = True
            elif s.kind == "section":
                depth = 1 if has_title_root else 0
                entries.append((i, s.title, depth))
            else:
                entries.append((i, s.title, 0))

        if entries:
            toc = Slide(title="目录", body="", kind="toc", index=0)
            # Shift every original slide's index by +1 to make room for the
            # TOC at position 0; TOC entries point into the *new* list.
            self.slides = [toc] + [
                Slide(title=s.title, body=s.body, kind=s.kind, index=i + 1)
                for i, s in enumerate(parsed)
            ]
            self.toc_entries = [(i + 1, t, d) for (i, t, d) in entries]
        else:
            self.slides = parsed
            self.toc_entries = []

        self.index = max(0, min(self.index, len(self.slides) - 1))
        self.toc_selection = max(0, min(self.toc_selection, max(0, len(self.toc_entries) - 1)))
        self.scroll = 0

    def current(self) -> Slide:
        return self.slides[self.index]

    # --- rendering ---

    def _render(self):
        w, h = self.console.size
        theme = get_theme(self.theme_name)
        if self.show_help:
            return render_help(theme, w, h)
        if self.current().kind == "toc":
            self.max_scroll = 0
            self.scroll = 0
            return render_toc(
                entries=self.toc_entries,
                selection=self.toc_selection,
                theme=theme,
                width=w,
                height=h,
                file_name=self.file_path.name,
                page=self.index + 1,
                total=len(self.slides),
            )
        renderable, max_scroll = render_slide(
            self.current(),
            theme=theme,
            base_dir=self.file_path.parent,
            width=w,
            height=h,
            file_name=self.file_path.name,
            page=self.index + 1,
            total=len(self.slides),
            scroll=self.scroll,
            console=self.console,
        )
        # Renderer clamps `scroll` to the content's real bounds; sync our copy
        # so subsequent key presses decide "am I at the edge?" correctly.
        self.max_scroll = max_scroll
        self.scroll = max(0, min(self.scroll, max_scroll))
        return renderable

    # --- main loop ---

    def _paint(self) -> None:
        """Redraw the current slide in place.

        Uses ``\\x1b[H`` (cursor home) instead of ``\\x1b[2J`` (full clear)
        to avoid the flash users perceive on every slide change — most
        visible on image slides, whose OSC 1337 payload takes enough time
        to transmit that a blanked screen is clearly visible. Trailing
        ``\\x1b[J`` (erase-below) cleans up rows a taller previous frame
        may have left after a resize.

        Pushing the theme's rich styles per frame is what lets ``Markdown``
        pick up our ``markdown.code``/``markdown.link``/``markdown.block_quote``
        overrides without plumbing a Theme through ``render_slide``.
        """
        theme = get_theme(self.theme_name)
        self.console.push_theme(theme.rich_theme())
        try:
            out = self.console.file
            out.write("\x1b[H")
            self.console.print(self._render(), end="")
            out.write("\x1b[J")
            out.flush()
        finally:
            self.console.pop_theme()

    def run(self) -> None:
        with raw_mode():
            # Manually enter the alternate screen buffer so we own the viewport
            # (and exit it cleanly on quit). This is what `Live(screen=True)`
            # does internally, but doing it ourselves means we control exactly
            # when each frame gets flushed — Terminal.app + auto_refresh=False
            # was losing the first frame otherwise.
            self.console.file.write("\x1b[?1049h\x1b[H\x1b[2J")
            self.console.file.flush()
            try:
                self._paint()
                while True:
                    key = read_key()
                    action = self._handle(key)
                    if action == "quit":
                        break
                    if action == "pick":
                        # Temporarily leave alt screen to show the file picker,
                        # then re-enter for the slideshow.
                        self.console.file.write("\x1b[?1049l")
                        self.console.file.flush()
                        new_file = pick_file(
                            self.console, get_theme(self.theme_name), self.file_path.parent
                        )
                        if new_file is not None:
                            self.file_path = new_file
                            self.index = 0
                            self.reload()
                        self.console.file.write("\x1b[?1049h\x1b[H\x1b[2J")
                        self.console.file.flush()
                    self._paint()
            finally:
                self.console.file.write("\x1b[?1049l")
                self.console.file.flush()

    # --- key dispatch ---

    def _goto(self, i: int) -> None:
        new_index = max(0, min(len(self.slides) - 1, i))
        if new_index != self.index:
            self.index = new_index
            self.scroll = 0

    def _scroll_step(self) -> int:
        """Lines to move per ↑/↓ / PageUp / PageDn press — one full viewport.

        The user asked for 'flip the whole page' behavior rather than a few
        lines at a time, so every scroll key advances by body_h rows and the
        page counter in the footer ticks 1 → 2 → 3.
        """
        _, h = self.console.size
        return body_viewport_height(h)

    _page_step = _scroll_step

    def _jump_to_toc(self) -> None:
        """Jump to the TOC and sync selection to the current slide."""
        if not self.toc_entries:
            return
        # Highlight the entry whose target slide is <= the current slide, so
        # pressing `c` mid-deck lands on the nearest heading above you.
        best = 0
        for i, entry in enumerate(self.toc_entries):
            if entry[0] <= self.index:
                best = i
        self.toc_selection = best
        self._goto(0)

    def _handle(self, key) -> str | None:
        # Help overlay: any key closes it
        if self.show_help:
            if key in (Key.CTRL_C,) or key == "q":
                return "quit"
            self.show_help = False
            return None

        on_toc = self.current().kind == "toc"

        # Number-then-Enter = jump to slide N. On the TOC we still let users
        # type a number + Enter to jump by slide number; a bare Enter without
        # a buffered number is reserved for "jump to highlighted entry".
        if isinstance(key, str) and key.isdigit():
            self.number_buffer += key
            return None
        if key == Key.ENTER and self.number_buffer:
            try:
                n = int(self.number_buffer)
                self._goto(n - 1)
            except ValueError:
                pass
            self.number_buffer = ""
            return None
        # Drop a partial number buffer on any other keypress.
        self.number_buffer = ""

        if key in (Key.CTRL_C,) or key == "q":
            return "quit"

        # Jump-to-contents from anywhere.
        if key == "c" and self.toc_entries:
            self._jump_to_toc()
            return None

        # TOC mode: ↑/↓/j/k move selection, Enter jumps to it. Every other
        # key falls through to the normal slide dispatch below (so →/Space/g
        # etc. still work as expected from the contents page).
        if on_toc and self.toc_entries:
            if key in (Key.UP, "k"):
                self.toc_selection = max(0, self.toc_selection - 1)
                return None
            if key in (Key.DOWN, "j"):
                self.toc_selection = min(
                    len(self.toc_entries) - 1, self.toc_selection + 1
                )
                return None
            if key == Key.ENTER:
                slide_idx = self.toc_entries[self.toc_selection][0]
                self._goto(slide_idx)
                return None
        # ESC intentionally does NOT quit: arrow keys start with \x1b and a
        # single delayed byte would otherwise get misread as "user pressed ESC".

        # ↓ / ↑ : scroll within slide first; once the viewport hits the edge,
        # hand the keypress off to slide navigation (PDF-reader behavior).
        # ← / → / Space / Enter etc. always navigate — they're unambiguous.
        if key in (Key.DOWN, Key.PAGE_DOWN):
            step = self._scroll_step() if key == Key.DOWN else self._page_step()
            if self.scroll < self.max_scroll:
                self.scroll = min(self.max_scroll, self.scroll + step)
                return None
            self._goto(self.index + 1)
            return None
        if key in (Key.UP, Key.PAGE_UP):
            step = self._scroll_step() if key == Key.UP else self._page_step()
            if self.scroll > 0:
                self.scroll = max(0, self.scroll - step)
                return None
            self._goto(self.index - 1)
            return None

        # Vim-style j/k kept as scroll aliases when there's room, else navigate
        if key == "j":
            if self.scroll < self.max_scroll:
                self.scroll = min(self.max_scroll, self.scroll + self._scroll_step())
                return None
            self._goto(self.index + 1)
            return None
        if key == "k":
            if self.scroll > 0:
                self.scroll = max(0, self.scroll - self._scroll_step())
                return None
            self._goto(self.index - 1)
            return None

        # Next (always advance the slide, even mid-scroll)
        if key in (Key.RIGHT, Key.SPACE, Key.ENTER) or key in ("l", "n"):
            self._goto(self.index + 1)
            return None
        # Prev
        if key in (Key.LEFT, Key.BACKSPACE) or key in ("h", "p"):
            self._goto(self.index - 1)
            return None
        if key == Key.HOME or key == "g":
            self._goto(0)
            return None
        if key == Key.END or key == "G":
            self._goto(len(self.slides) - 1)
            return None
        if key == "r":
            self.reload()
            return None
        if key == "t":
            self.theme_name = next_theme(self.theme_name)
            return None
        if key == "o":
            return "pick"
        if key == "?":
            self.show_help = True
            return None
        return None
