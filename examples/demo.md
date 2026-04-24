# Lantern

Render any Markdown as a slideshow, right in your terminal.

> Press `→` or `Space` to go forward, `←` to go back, `?` for help, `q` to quit.

---

# Why another slides tool?

- No browser, no HTML, no Node toolchain — just your terminal
- Markdown in, slides out; the file *is* the source of truth
- Navigation, themes, images, fuzzy file picker all built-in

**Key idea**: treat `# Heading` as a slide break. If there's no `#`, fall back to `##`.

# Features at a glance

| Feature            | Supported                         |
| ------------------ | --------------------------------- |
| Markdown           | headings, lists, tables, quotes   |
| Code highlighting  | yes — via `rich` + pygments       |
| Images             | half-block 24-bit color (any term)|
| Navigation         | arrows, vim keys, jump-to-N       |
| File picker        | fuzzy, recursive, `o` to re-open  |
| Themes             | dark · light · mono (`t` to cycle)|

# Code looks good too

```python
def parse_slides(text: str) -> list[Slide]:
    if _count_headings(text, 1) >= 1:
        return _split_by_level(text, 1)
    if _count_headings(text, 2) >= 1:
        return _split_by_level(text, 2)
    return [Slide(title=None, body=text, index=0)]
```

```bash
# Run it
slide examples/demo.md

# Or without args — shows a drag-and-drop prompt
slide
```

# Lists work, too

1. **Bold** and *italic* text
2. `inline code` and [links](https://example.com)
3. Nested:
   - first sublevel
   - second sublevel
     - third sublevel
4. Back to top

> Blockquotes get a nice left bar and dim styling.

# Keyboard shortcuts

- `→` / `Space` / `Enter` — next
- `←` / `Backspace` — previous
- `g` / `G` — first / last
- `<N>` then `Enter` — jump to slide N
- `o` — open another file
- `r` — reload
- `t` — cycle theme
- `?` — this help
- `q` — quit

# Thanks

Made with **Python**, **rich**, and **Pillow**.

The entire thing fits in under 700 lines.

# A picture

![gradient demo](test.png)

Images render as half-block glyphs — two pixels per character cell.
