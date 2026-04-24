"""Color themes for Lantern.

Palettes tuned for long-form technical reading — restrained accents, high
contrast on body text, and inline code that sits on a quiet tint instead of a
reverse-color block. Every style string is either a hex color ("#xxxxxx"),
a rich style name, or a compound like "#fg on #bg". Fields beyond the basics
(``heading``, ``inline_code``, ``block_quote``, ``link``, …) are injected
into a ``rich.theme.Theme`` so that markdown rendering in ``renderer.py``
picks them up without having to subclass every element.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.theme import Theme as RichTheme


@dataclass(frozen=True)
class Theme:
    name: str
    # Panel chrome ----------------------------------------------------------
    title: str               # slide title Text (title/section slides) + panel title
    accent: str              # brand accents — bullets, numbers, panel title text
    border: str              # panel border
    bg: str                  # panel interior bg; "" = transparent (terminal bg)
    # Body text --------------------------------------------------------------
    text: str                # default body text (outside markdown)
    text_muted: str          # dim / secondary
    footer: str              # footer line
    # Markdown-specific (full rich style strings, may include "on #bg") -------
    heading: str             # H1..H6 inside markdown bodies
    inline_code: str         # `code` — fg + bg, never reverse-video
    block_quote: str         # blockquote body text
    block_quote_border: str  # the ▌ bar color (distinct from body)
    link: str                # [text](url)
    # Progress indicator -----------------------------------------------------
    progress_filled: str
    progress_empty: str
    progress_chars: tuple[str, str]   # (filled, empty); thin line chars by default
    # Pygments theme for fenced code blocks
    code_theme: str

    def __post_init__(self) -> None:
        # Precompute derived values once per theme singleton — callers hit
        # panel_style() / rich_theme() on every repaint, and rebuilding a
        # RichTheme dict per keypress is wasted work on frozen singletons.
        object.__setattr__(self, "_panel_style", self._compute_panel_style())
        object.__setattr__(self, "_rich_theme", self._compute_rich_theme())

    def panel_style(self) -> str:
        return self._panel_style  # type: ignore[attr-defined]

    def rich_theme(self) -> RichTheme:
        return self._rich_theme  # type: ignore[attr-defined]

    def _compute_panel_style(self) -> str:
        # Pin both fg and bg so a dark panel stays readable in a
        # light-profile terminal (and vice versa) — otherwise body text
        # inherits the terminal's default fg and you get black-on-dark.
        parts: list[str] = []
        if self.text and self.text != "default":
            parts.append(self.text)
        if self.bg:
            parts.append(f"on {self.bg}")
        return " ".join(parts)

    def _compute_rich_theme(self) -> RichTheme:
        # ``markdown.block_quote.border`` is a custom key — renderer's
        # _SlideBlockQuote reads it via Console.get_style to paint the ▌
        # bar separately from the quote body.
        return RichTheme(
            {
                "markdown.h1": self.heading,
                "markdown.h2": self.heading,
                "markdown.h3": self.heading,
                "markdown.h4": self.heading,
                "markdown.h5": self.heading,
                "markdown.h6": self.heading,
                "markdown.code": self.inline_code,
                "markdown.link": self.link,
                "markdown.link_url": self.link,
                "markdown.block_quote": self.block_quote,
                "markdown.block_quote.border": self.block_quote_border,
                "markdown.item.bullet": self.accent,
                "markdown.item.number": self.accent,
                "markdown.hr": self.border,
                # Rich defaults these to bare ``cyan`` which clashes with
                # every palette we ship.
                "markdown.table.header": self.heading,
                "markdown.table.border": self.border,
            },
            inherit=True,
        )


# ── LIGHT ────────────────────────────────────────────────────────────────
# Warm academic: off-white base, deep purple-gray text, teal + rose accents.
LIGHT = Theme(
    name="light",
    title="bold #575279",
    accent="bold #286983",
    border="#dfdad9",
    bg="#faf4ed",
    text="#575279",
    text_muted="#797593",
    footer="#9893a5",
    heading="bold #575279",
    inline_code="#b4637a on #f2e9e1",
    block_quote="#575279",
    block_quote_border="#286983",
    link="#56949f",
    progress_filled="#286983",
    progress_empty="#dfd8cc",
    progress_chars=("━", "─"),
    code_theme="friendly",
)


# ── DARK ─────────────────────────────────────────────────────────────────
# Soft dark-gray card (never pure black) with muted pastel accents.
DARK = Theme(
    name="dark",
    title="bold #e6e6e6",
    accent="bold #7aa2f7",
    border="#3b4261",
    bg="#1e1e24",
    text="#c0caf5",
    text_muted="#737aa2",
    footer="#565f89",
    heading="bold #e6e6e6",
    inline_code="#c0caf5 on #2a2e3f",
    block_quote="#a9b1d6",
    block_quote_border="#7aa2f7",
    link="#7dcfff",
    progress_filled="#7aa2f7",
    progress_empty="#2a2e3f",
    progress_chars=("━", "─"),
    code_theme="monokai",
)


# ── MONO ─────────────────────────────────────────────────────────────────
# Colorless fallback for low-capability terminals — no bg tint, rich defaults.
MONO = Theme(
    name="mono",
    title="bold",
    accent="bold",
    border="grey70",
    bg="",
    text="default",
    text_muted="dim",
    footer="dim",
    heading="bold",
    inline_code="reverse",
    block_quote="dim",
    block_quote_border="default",
    link="underline",
    progress_filled="default",
    progress_empty="grey23",
    progress_chars=("━", "─"),
    code_theme="ansi_dark",
)


_THEMES: dict[str, Theme] = {"dark": DARK, "light": LIGHT, "mono": MONO}


def get_theme(name: str) -> Theme:
    return _THEMES.get(name, DARK)


def next_theme(name: str) -> str:
    keys = list(_THEMES.keys())
    try:
        i = keys.index(name)
    except ValueError:
        return keys[0]
    return keys[(i + 1) % len(keys)]


def all_theme_names() -> list[str]:
    return list(_THEMES.keys())
