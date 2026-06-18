"""Generate ``packaging/storageanalyzer.ico`` -- the application icon.

The icon is a stylised squarified treemap (the same visual the HTML report
draws): a rounded tile partitioned into a few nested rectangles. It is checked
in as a binary so the exe build never depends on Pillow; this script exists only
to regenerate / tweak it.

    python packaging/make_icon.py        # rewrites packaging/storageanalyzer.ico

Requires Pillow (``pip install pillow``).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Palette -- a cool blue/teal treemap on a dark rounded tile.
_BG = (24, 28, 38, 255)
_BORDER = (15, 18, 26, 255)
_TILES = [
    # (x0, y0, x1, y1, fill)  -- in a 0..1 unit square, drawn largest-first
    (0.06, 0.06, 0.60, 0.62, (56, 132, 222, 255)),   # big blue block
    (0.62, 0.06, 0.94, 0.40, (88, 196, 214, 255)),   # teal
    (0.62, 0.42, 0.94, 0.62, (122, 162, 247, 255)),  # periwinkle
    (0.06, 0.64, 0.36, 0.94, (94, 214, 168, 255)),   # green
    (0.38, 0.64, 0.60, 0.94, (240, 190, 92, 255)),   # amber
    (0.62, 0.64, 0.94, 0.94, (233, 116, 122, 255)),  # red
]


def _render(size: int) -> Image.Image:
    """Render the icon at ``size`` x ``size`` px with a rounded background."""
    # Supersample for crisp edges, then downscale.
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(s * 0.18)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=_BG,
                        outline=_BORDER, width=max(1, int(s * 0.012)))

    gap = s * 0.012
    tile_r = max(1, int(s * 0.04))
    for x0, y0, x1, y1, fill in _TILES:
        box = [
            x0 * s + gap, y0 * s + gap,
            x1 * s - gap, y1 * s - gap,
        ]
        d.rounded_rectangle(box, radius=tile_r, fill=fill)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).with_name("storageanalyzer.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [_render(n) for n in sizes]
    # Pillow writes a proper multi-resolution .ico from the largest frame +
    # the explicit sizes list.
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in sizes])
    print(f"wrote {out} ({out.stat().st_size:,} bytes, sizes={sizes})")


if __name__ == "__main__":
    main()
