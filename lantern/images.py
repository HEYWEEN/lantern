"""Render images to terminal.

Two backends:

* ``iterm2`` — iTerm2's inline images protocol (OSC 1337 ``File=``). Emits
  the original pixels; the terminal rasterises them. Used automatically
  when ``$TERM_PROGRAM == "iTerm.app"`` (or ``$LC_TERMINAL == "iTerm2"``,
  which is what iTerm sets inside tmux). True-colour fidelity.

* ``ascii`` — Unicode half-block (``▀``) with 24-bit fg/bg. Every cell
  encodes two vertical pixels. Works in every truecolour terminal and is
  the default fallback for Terminal.app / ssh / unknown terminals.

Sources supported:
  * absolute / relative filesystem paths (resolved against the slide deck)
  * http(s) URLs (downloaded once, cached under ~/.cache/lantern/images)
"""

from __future__ import annotations

import base64
import hashlib
import os
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    _PIL_OK = False


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def _is_iterm2() -> bool:
    """True when we're running inside iTerm2 (direct or via tmux).

    iTerm sets ``TERM_PROGRAM=iTerm.app`` directly and, additionally, exports
    ``LC_TERMINAL=iTerm2`` via LC_* so the hint survives tmux / ssh. Check
    both so the protocol works in common nested setups.
    """
    if os.environ.get("TERM_PROGRAM") == "iTerm.app":
        return True
    if os.environ.get("LC_TERMINAL") == "iTerm2":
        return True
    return False


def detect_protocol() -> str:
    """Return the image backend to use: ``iterm2`` or ``ascii``.

    ``LANTERN_IMG_MODE`` overrides detection (useful for forcing the ASCII
    fallback in iTerm when dogfooding, or vice-versa).
    """
    override = os.environ.get("LANTERN_IMG_MODE")
    if override:
        return override
    if _is_iterm2():
        return "iterm2"
    return "ascii"


def _is_url(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def _cache_dir() -> Path:
    override = os.environ.get("LANTERN_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "lantern" / "images"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _fetch_url(
    url: str,
    timeout: float = 8.0,
    max_bytes: int = 20 * 1024 * 1024,
) -> Path | None:
    """Download `url` to the local cache and return the file path.

    Cached by SHA-256 of the URL so repeated renders of the same slide (or
    re-launches of lantern) don't refetch. Returns None on failure so callers
    can fall back to a placeholder instead of crashing.
    """
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if ext not in _IMAGE_EXTS:
        ext = ""
    cache_file = _cache_dir() / f"{key}{ext}"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file
    try:
        req = urllib.request.Request(
            url,
            headers={
                # Some CDNs (notably jsDelivr, githubusercontent) refuse the
                # default urllib UA with 403. A realistic UA avoids that.
                "User-Agent": (
                    "Mozilla/5.0 (Lantern terminal presenter; +https://github.com/)"
                ),
                "Accept": "image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # +1 lets us detect overflow without silently truncating
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
        tmp = cache_file.with_suffix(cache_file.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(cache_file)
        return cache_file
    except Exception:
        return None


def resolve_image_source(src: str, base_dir: Path) -> Path | None:
    """Turn a markdown image src (URL or path) into a readable local file.

    Returns None if the image can't be located or downloaded.
    """
    src = src.strip()
    if _is_url(src):
        return _fetch_url(src)
    p = Path(src).expanduser()
    if not p.is_absolute():
        p = (base_dir / p).expanduser()
    return p if p.exists() else None


def _fit_to_cells(img: "Image.Image", max_w_cells: int, max_h_cells: int) -> "Image.Image":
    """Scale image so it fits in (max_w_cells × max_h_cells) character cells,
    where each cell represents 1 horizontal pixel and 2 vertical pixels.
    """
    target_w = max(1, max_w_cells)
    target_h = max(1, max_h_cells * 2)
    w, h = img.size
    if w == 0 or h == 0:
        return img
    ratio = min(target_w / w, target_h / h, 1.0)
    new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def _render_half_blocks(img: "Image.Image") -> str:
    img = img.convert("RGB")
    w, h = img.size
    if h % 2 == 1:
        padded = Image.new("RGB", (w, h + 1), (0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded
        h += 1

    px = img.load()
    lines: list[str] = []
    for y in range(0, h, 2):
        parts: list[str] = []
        last_fg: tuple | None = None
        last_bg: tuple | None = None
        for x in range(w):
            fg = px[x, y]
            bg = px[x, y + 1]
            if fg != last_fg:
                parts.append(f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m")
                last_fg = fg
            if bg != last_bg:
                parts.append(f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m")
                last_bg = bg
            parts.append("▀")  # ▀
        parts.append("\x1b[0m")
        lines.append("".join(parts))
    return "\n".join(lines)


def render_image(path: Path, max_w_cells: int, max_h_cells: int) -> tuple[str, int, int]:
    """Return (ansi_string, width_cells, height_cells). On failure returns
    a human-readable placeholder and (0, 0)."""
    if not _PIL_OK:
        return (f"[image: Pillow not installed — {path.name}]", 0, 0)
    if not path.exists():
        return (f"[missing image: {path}]", 0, 0)
    try:
        img = Image.open(path)
    except Exception as e:
        return (f"[image error: {path.name} — {e}]", 0, 0)

    img = _fit_to_cells(img, max_w_cells, max_h_cells)
    w, h = img.size
    out = _render_half_blocks(img)
    cell_h = (h + 1) // 2
    return (out, w, cell_h)


# --- iTerm2 inline images -------------------------------------------------
#
# We return the raw OSC 1337 ``File=...`` payload (BEL-terminated) without a
# save/restore wrapper. The caller (renderer._ITerm2Image) is responsible for
# positioning the cursor at the top-left of the reserved rectangle *after*
# the blank cells have been emitted, so the image isn't overwritten by its
# own placeholder spaces — writing ordinary text to image cells in iTerm2
# replaces them with text cells, which was the bug we had when the image
# escape came first and the blank reservation came after.

# Module-level cache so we don't re-encode base64 every repaint. Keyed by
# (path, mtime, w_cells, h_cells); small because presentations are small.
_ITERM_CACHE: dict[tuple[str, int, int, int], tuple[str, int, int]] = {}


def _compute_iterm2_cells(
    img_w: int, img_h: int, max_w_cells: int, max_h_cells: int
) -> tuple[int, int]:
    """Fit (img_w, img_h) pixels into (max_w_cells, max_h_cells) character
    cells, assuming a cell is roughly twice as tall as it is wide.

    Used only to decide how many cells to *reserve*; the terminal does the
    actual resampling from the full-resolution source.
    """
    if img_w <= 0 or img_h <= 0:
        return (max(1, max_w_cells), max(1, max_h_cells))
    cell_aspect = 2.0  # height/width ratio of a typical monospace cell
    # Aspect ratio in cells: cells_h / cells_w = (h_px / w_px) / cell_aspect
    img_ratio = (img_h / img_w) / cell_aspect
    w_cells = max(1, min(max_w_cells, max_w_cells))
    h_cells = max(1, int(round(w_cells * img_ratio)))
    if h_cells > max_h_cells:
        h_cells = max(1, max_h_cells)
        w_cells = max(1, min(max_w_cells, int(round(h_cells / img_ratio))))
    return (w_cells, h_cells)


def render_iterm2_image(
    path: Path, max_w_cells: int, max_h_cells: int
) -> tuple[str, int, int] | None:
    """Build the iTerm2 inline-image payload for ``path``.

    Returns ``(osc_payload, width_cells, height_cells)``. ``osc_payload`` is
    the bare ``\\x1b]1337;File=...\\x07`` sequence — draws the image at the
    terminal's current cursor position and advances the cursor past the
    image. The caller is expected to (a) reserve ``width×height`` blank
    cells first, (b) move the cursor back to the top-left of that rectangle,
    (c) emit this payload, (d) restore the cursor. Returns ``None`` if the
    image can't be read (caller falls back to a placeholder).
    """
    if not path.exists():
        return None
    try:
        st = path.stat()
    except OSError:
        return None

    # Probe image dimensions with Pillow when available; otherwise fall back
    # to filling the slot and letting iTerm2 scale (preserveAspectRatio=1).
    img_w = img_h = 0
    if _PIL_OK:
        try:
            with Image.open(path) as im:
                img_w, img_h = im.size
        except Exception:
            pass

    w_cells, h_cells = _compute_iterm2_cells(img_w, img_h, max_w_cells, max_h_cells)

    cache_key = (str(path), int(st.st_mtime), w_cells, h_cells)
    hit = _ITERM_CACHE.get(cache_key)
    if hit is not None:
        return hit

    try:
        data = path.read_bytes()
    except OSError:
        return None

    name_b64 = base64.b64encode(path.name.encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(data).decode("ascii")
    args = ";".join(
        [
            f"name={name_b64}",
            f"size={len(data)}",
            f"width={w_cells}",
            f"height={h_cells}",
            "preserveAspectRatio=1",
            "inline=1",
        ]
    )
    # Bare OSC 1337 — save/restore cursor is applied by the renderer after
    # positioning the cursor at the rectangle's top-left.
    escape = f"\x1b]1337;File={args}:{payload_b64}\x07"
    result = (escape, w_cells, h_cells)
    _ITERM_CACHE[cache_key] = result
    # Bound cache growth in case someone flips through a huge deck.
    if len(_ITERM_CACHE) > 64:
        # Drop an arbitrary oldest entry (insertion-ordered dict).
        _ITERM_CACHE.pop(next(iter(_ITERM_CACHE)))
    return result
