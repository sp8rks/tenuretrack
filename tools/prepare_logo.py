"""Turn the source logo artwork into the assets the repo actually uses.

The artwork arrives as a flat PNG on an almost-white background: 1254 by 1254,
839 KB, and 19,394 distinct colours, nearly all of them one or two levels of
noise around white. Dropped into a README or a slide as it is, it carries a
white rectangle across whatever it sits on and costs most of a megabyte.

This does three things and nothing else. It floods the background away from the
four corners, which leaves the white dashes inside the road alone because they
are enclosed by dark pixels and the flood never reaches them. It crops to the
ink. It writes two sizes: the whole lockup, and the graphic on its own for the
places a wordmark would be too wide to read.

Run `make logo` after replacing the source artwork. Nothing else in the build
depends on this script; the assets it writes are committed.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "tenuretrack-logo-source.png"
ASSETS = ROOT / "src" / "tenuretrack" / "assets"
"""Written inside the package, not beside it.

The Colab path pip-installs tenuretrack straight from GitHub, so a report
built there can only reach a file that shipped in the wheel. The master
artwork stays in `assets/` at the root, where it is not packaged: it is
nearly a megabyte and nothing at runtime reads it.
"""

FLOOD_SENTINEL = (255, 0, 255)
"""A colour the artwork does not contain, so the fill can be found again."""

FLOOD_TOLERANCE = 30
"""Wide enough to swallow the near-white noise, narrow enough to stop at ink."""

LOCKUP_WIDTH = 1200
MARK_SIDE = 512
PAD = 8

MARK_GAP_SHARE = 0.025
"""How much clear height counts as a break between parts of the lockup.

Small enough to catch the band under the graphic, large enough to ignore the
one-pixel rows between the dot of an i and its stem.
"""


def _drop_background(image: Image.Image) -> Image.Image:
    """Make the outer background transparent, from the corners inward."""
    flat = image.convert("RGB")
    width, height = flat.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ImageDraw.floodfill(flat, corner, FLOOD_SENTINEL, thresh=FLOOD_TOLERANCE)

    out = flat.convert("RGBA")
    pixels = out.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y][:3] == FLOOD_SENTINEL:
                pixels[x, y] = (255, 255, 255, 0)
    return out


def _trim(image: Image.Image, pad: int = PAD) -> Image.Image:
    box = image.getchannel("A").getbbox()
    if box is None:  # pragma: no cover - an empty image is a bug upstream
        return image
    cropped = image.crop(box)
    out = Image.new(
        "RGBA", (cropped.width + 2 * pad, cropped.height + 2 * pad), (255, 255, 255, 0)
    )
    out.paste(cropped, (pad, pad))
    return out


def _ink_rows(image: Image.Image) -> list[int]:
    """Row indices holding any ink, used to find the blank band under the graphic."""
    alpha = image.getchannel("A")
    return [
        y
        for y in range(image.height)
        if alpha.crop((0, y, image.width, y + 1)).getextrema()[1] > 8
    ]


def _split_mark(image: Image.Image) -> Image.Image:
    """Everything above the first real blank band, which sits under the graphic.

    Found rather than hardcoded, because a redraw of the artwork moves the
    wordmark and a hardcoded row would quietly slice through it. The first wide
    gap and not the widest: this lockup has two gaps of nearly equal size, the
    one under the graphic and the one above the tagline, and the widest is the
    wrong one about half the time.
    """
    rows = _ink_rows(image)
    least = max(4, round(image.height * MARK_GAP_SHARE))
    for first, second in zip(rows, rows[1:], strict=False):
        if second - first >= least:
            return _trim(image.crop((0, 0, image.width, first + 1)))
    return _trim(image)


def _square(image: Image.Image, side: int) -> Image.Image:
    """Centre the artwork on a square with room to breathe on its long edge.

    A mark is used as an avatar and a favicon, where something touching the
    edge reads as clipped rather than as full-bleed.
    """
    edge = round(max(image.size) * 1.08)
    canvas = Image.new("RGBA", (edge, edge), (255, 255, 255, 0))
    canvas.paste(image, ((edge - image.width) // 2, (edge - image.height) // 2))
    return canvas.resize((side, side), Image.LANCZOS)


def _compact(image: Image.Image) -> Image.Image:
    """Cut the palette down where it costs nothing visible.

    The artwork is flat colour with antialiased edges, and it arrived carrying
    19,394 distinct colours, almost all of them noise around white. 255 of them
    render the same and store in a fraction of the space. Fast octree because
    it is the only method Pillow will run on an image with an alpha channel,
    and it carries the transparency through itself.
    """
    return image.quantize(colors=255, method=Image.FASTOCTREE, dither=Image.NONE)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE)
    clean = _trim(_drop_background(source))

    lockup = clean.resize(
        (LOCKUP_WIDTH, round(clean.height * LOCKUP_WIDTH / clean.width)),
        Image.LANCZOS,
    )
    lockup_path = ASSETS / "tenuretrack-logo.png"
    _compact(lockup).save(lockup_path, optimize=True)

    mark_path = ASSETS / "tenuretrack-mark.png"
    _compact(_square(_split_mark(clean), MARK_SIDE)).save(
        mark_path, optimize=True
    )

    for path in (lockup_path, mark_path):
        with Image.open(path) as done:
            print(f"{path.relative_to(ROOT)}  {done.size[0]}x{done.size[1]}  "
                  f"{path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
