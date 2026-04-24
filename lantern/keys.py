"""Raw-mode single-key keyboard reader for macOS / Linux.

We intentionally avoid curses / textual; a termios raw-mode loop plus manual
escape-sequence parsing is enough for what a slideshow needs.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import tty
from contextlib import contextmanager
from enum import Enum


class Key(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    UP = "UP"
    DOWN = "DOWN"
    HOME = "HOME"
    END = "END"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"
    ENTER = "ENTER"
    SPACE = "SPACE"
    TAB = "TAB"
    BACKSPACE = "BACKSPACE"
    ESC = "ESC"
    CTRL_C = "CTRL_C"


@contextmanager
def raw_mode(fd: int | None = None):
    """Put the tty in cbreak mode for the duration of the block.

    We deliberately use cbreak (not full raw / `tty.setraw`). Full raw clears
    OPOST, which disables the kernel's NL -> CR-NL translation on *output*.
    That breaks our rendering loop: Rich ends each line with a bare `\\n`, and
    without OPOST the cursor only moves down — it never returns to column 1,
    so each successive line gets emitted further and further to the right and
    the whole slide walks diagonally off-screen.

    cbreak gives us what we actually want: characters delivered one at a time
    without echo or line buffering (for input), while leaving output post-
    processing untouched.
    """
    if fd is None:
        fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_byte() -> str:
    """Read ONE byte, blocking, using os.read to bypass Python's stdin buffer.

    Why not sys.stdin.read(1)? Python's TextIOWrapper / BufferedReader greedily
    slurps multiple bytes from the OS fd on the first read. A multi-byte arrow
    key (\\x1b[C) can all land in Python's buffer at once, after which select()
    on the fd sees nothing — desync. os.read goes straight to the OS queue and
    stays in sync with select().
    """
    try:
        b = os.read(sys.stdin.fileno(), 1)
    except OSError:
        return ""
    if not b:
        return ""
    # Keys we care about are ASCII; latin-1 is byte-safe for non-ASCII input
    return b.decode("latin-1")


def _peek(timeout: float = 0.05) -> str:
    """Non-blocking read with timeout — used to disambiguate bare ESC from
    the start of a CSI/SS3 sequence."""
    ready, _, _ = select.select([sys.stdin.fileno()], [], [], timeout)
    if not ready:
        return ""
    return _read_byte()


def read_key() -> Key | str:
    """Block until one logical key event arrives. Returns a Key enum or a single char."""
    ch = _read_byte()
    if ch == "":
        return Key.ESC
    if ch == "\x03":
        return Key.CTRL_C
    if ch in ("\r", "\n"):
        return Key.ENTER
    if ch == " ":
        return Key.SPACE
    if ch == "\t":
        return Key.TAB
    if ch in ("\x7f", "\x08"):
        return Key.BACKSPACE
    if ch != "\x1b":
        return ch

    # \x1b arrived — could be bare ESC, or the start of a CSI/SS3 sequence.
    # Use a short timeout to peek the next byte. Raising this too high makes
    # a real ESC press feel laggy; too low and arrow keys get misread as ESC.
    nxt = _peek(timeout=0.05)
    if nxt == "":
        return Key.ESC
    if nxt not in ("[", "O"):
        # Bare ESC followed by an unrelated key — report ESC and drop the rest.
        return Key.ESC

    # We're committed to a multi-byte escape sequence. The terminal always
    # delivers the remaining bytes back-to-back, so blocking reads are safe.
    code = _read_byte()
    mapping_csi = {
        "A": Key.UP, "B": Key.DOWN, "C": Key.RIGHT, "D": Key.LEFT,
        "H": Key.HOME, "F": Key.END,
    }
    if code in mapping_csi:
        return mapping_csi[code]
    if code.isdigit():
        # CSI <n> [;<m>] ~  (e.g. \x1b[5~ for PageUp)
        number = code
        while True:
            n = _read_byte()
            if n == "~":
                tilde_map = {
                    "1": Key.HOME, "7": Key.HOME,
                    "4": Key.END, "8": Key.END,
                    "5": Key.PAGE_UP, "6": Key.PAGE_DOWN,
                }
                return tilde_map.get(number, Key.ESC)
            if n.isdigit() or n == ";":
                number += n
                continue
            return Key.ESC
    return Key.ESC
