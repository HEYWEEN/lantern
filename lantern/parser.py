"""Split a markdown document into slides.

Hierarchy rules:
- Scan headings (outside code fences) and take the two shallowest levels
  that actually appear in the document:
    * ``title_level``   -> standalone "title" slide (heading centered on
      its own page, like a chapter cover)
    * ``section_level`` -> "section" slide (heading at top, body below)
- If only one level is present, it still acts as ``title_level``: every
  such heading becomes a centered cover page, and any content beneath it
  becomes a separate untitled "body" slide.
- Headings deeper than ``section_level`` stay inside the body and are
  rendered as sub-headings by the markdown engine.

In other words: the shallowest heading level = cover page, the next one
down = content page. If the document has no H1, H2 is promoted to cover
and H3 becomes the content page, and so on.
"""

from __future__ import annotations

from dataclasses import dataclass


_FENCE_MARKERS = ("```", "~~~")


@dataclass
class Slide:
    title: str | None
    body: str              # markdown body WITHOUT the title heading line
    kind: str              # "title" | "section" | "body" | "toc"
    index: int             # 0-based position


def _heading_level(line: str) -> int:
    n = 0
    for ch in line:
        if ch == "#":
            n += 1
        else:
            break
    if n == 0:
        return 0
    rest = line[n:]
    if rest and rest[0] not in (" ", "\t"):
        return 0
    return n


def _is_heading(line: str, level: int) -> bool:
    return _heading_level(line) == level


def _iter_lines_with_fence_state(text: str):
    in_fence = False
    fence_marker: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence:
            for m in _FENCE_MARKERS:
                if stripped.startswith(m):
                    in_fence = True
                    fence_marker = m
                    break
        else:
            if fence_marker and stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = None
        yield line, in_fence


def _collect_heading_levels(text: str) -> list[int]:
    levels: set[int] = set()
    for line, in_fence in _iter_lines_with_fence_state(text):
        if in_fence:
            continue
        lvl = _heading_level(line)
        if lvl > 0:
            levels.add(lvl)
    return sorted(levels)


def _heading_text(line: str) -> str | None:
    return line.lstrip("#").strip() or None


def parse_slides(text: str) -> list[Slide]:
    if not text.strip():
        return [Slide(title=None, body="", kind="body", index=0)]

    levels = _collect_heading_levels(text)
    if not levels:
        return [Slide(title=None, body=text.strip("\n"), kind="body", index=0)]

    title_level = levels[0]
    section_level = levels[1] if len(levels) >= 2 else None

    slides: list[Slide] = []
    current_title: str | None = None
    current_kind: str = "body"
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_kind, current_body
        body_text = "\n".join(current_body).strip("\n")
        has_content = bool(body_text.strip())
        if current_kind == "title":
            slides.append(
                Slide(title=current_title, body="", kind="title", index=len(slides))
            )
            if has_content:
                slides.append(
                    Slide(title=None, body=body_text, kind="body", index=len(slides))
                )
        elif current_kind == "section":
            slides.append(
                Slide(
                    title=current_title,
                    body=body_text,
                    kind="section",
                    index=len(slides),
                )
            )
        else:  # "body" — leading content before any heading
            if has_content:
                slides.append(
                    Slide(title=None, body=body_text, kind="body", index=len(slides))
                )
        current_title = None
        current_kind = "body"
        current_body = []

    for line, in_fence in _iter_lines_with_fence_state(text):
        if not in_fence:
            lvl = _heading_level(line)
            if lvl == title_level:
                flush()
                current_title = _heading_text(line)
                current_kind = "title"
                continue
            if section_level is not None and lvl == section_level:
                flush()
                current_title = _heading_text(line)
                current_kind = "section"
                continue
        current_body.append(line)

    flush()

    if not slides:
        slides = [Slide(title=None, body=text.strip("\n"), kind="body", index=0)]
    # Re-index in case any slide was dropped.
    return [
        Slide(title=s.title, body=s.body, kind=s.kind, index=i)
        for i, s in enumerate(slides)
    ]
