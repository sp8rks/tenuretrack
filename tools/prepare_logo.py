"""Turn the source logo artwork into the assets the repo actually uses.

The artwork arrives flat on an almost-white background: 1254 by 1254, 839 KB,
and 19,394 distinct colours, nearly all of them a level or two of noise around
white. Two things have to happen to it before it can sit on a page.

**Undo the white.** Not "flood the background away from the corners", which was
the first attempt and was wrong twice over. It left every antialiased edge
pixel fully opaque, so the artwork wore a white halo that is invisible on a
white page and obvious on a dark one, and it could not reach the white inside
the counters of the letters, so each `e` and `a` carried a white blob. What it
has to do instead is treat white as the matte it is: recover each pixel's
coverage from how far it sits from white, then divide the white back out to get
the colour underneath. The road's dashes and the letter counters both become
transparent, which is right on both themes, because on a light page they show
white through and on a dark page they show dark.

**Make a second copy for dark mode.** Half this artwork is a near-black navy:
the wordmark's first half, the road, the trend line and its dots. On a dark
page that half disappears and the reader is left with a green `track` floating
over some coloured bars. Undoing the white first is what makes the recolour
possible, because after it every edge pixel carries its true colour rather than
a blend with the background, so swapping navy for a light ink catches the edges
too instead of leaving a dark fringe.

Run `make logo` after replacing the source artwork.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "tenuretrack-logo-source.png"
ASSETS = ROOT / "src" / "tenuretrack" / "assets"
"""Written inside the package, not beside it.

The Colab path pip-installs tenuretrack straight from GitHub, so a report built
there can only reach a file that shipped in the wheel. The master artwork stays
in `assets/` at the root, where it is not packaged: it is nearly a megabyte and
nothing at runtime reads it.
"""

OPAQUE_BELOW = 215.0
CLEAR_ABOVE = 250.0
"""The luminance band the artwork's edges live in.

Measured on the source, whose histogram is close to two spikes: 1,427,387
pixels above 248 and 135,490 below 215, with about 9,600 in between. So the
band is exactly the antialiased fringe, and the ramp across it touches neither
the ink nor the background.
"""

NAVY = np.array([25.0, 37.0, 53.0])
"""The artwork's near-black, measured as the mean of everything under lum 60."""

NAVY_SOLID = 70.0
NAVY_EDGE = 110.0
"""Colour distances from NAVY: swapped outright, then faded out by NAVY_EDGE.

The teal sits 123 away, so this separates the navy family from the artwork's
own colours without anyone drawing a mask by hand.
"""

DARK_MODE_INK = np.array([227.0, 233.0, 241.0])
"""What the navy becomes on a dark page. Cool, to stay in family with the bars."""

LOCKUP_WIDTH = 1200
MARK_SIDE = 512
PAD = 8

MARK_GAP_SHARE = 0.025
"""How much clear height counts as a break between parts of the lockup.

Small enough to catch the band under the graphic, large enough to ignore the
one-pixel rows between the dot of an i and its stem.
"""


def _unmatte(image: Image.Image) -> np.ndarray:
    """Recover colour and coverage from artwork painted onto white.

    Every pixel is read as `seen = a * ink + (1 - a) * white`. Coverage comes
    from luminance, which is monotonic in `a` for any ink darker than the
    background and which the two-spike histogram makes reliable here. Then the
    background is divided back out, so a half-covered edge pixel comes back as
    the ink's own colour at half alpha rather than as a pale version of it at
    full alpha. That is the whole difference between artwork that composites
    onto any background and artwork that only works on the one it was drawn on.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=float)
    luminance = rgb @ np.array([0.299, 0.587, 0.114])

    alpha = (CLEAR_ABOVE - luminance) / (CLEAR_ABOVE - OPAQUE_BELOW)
    np.clip(alpha, 0.0, 1.0, out=alpha)

    # Divide the white matte back out. Guarded, because at alpha 0 the pixel is
    # background and there is no colour underneath to recover.
    covered = alpha > 0.004
    safe = np.where(covered, alpha, 1.0)[:, :, None]
    ink = (rgb - 255.0 * (1.0 - safe)) / safe
    np.clip(ink, 0.0, 255.0, out=ink)

    out = np.zeros((*rgb.shape[:2], 4), dtype=float)
    out[:, :, :3] = np.where(covered[:, :, None], ink, 255.0)
    out[:, :, 3] = alpha * 255.0
    return out


def _for_dark_mode(rgba: np.ndarray) -> np.ndarray:
    """Swap the artwork's near-black for a light ink, edges included.

    Works on straight colour, which is why `_unmatte` has to run first. On the
    original an edge between the navy and the page is a pale blend that no
    threshold catches, and swapping only the solid centres would leave every
    letter and the whole road outlined in the colour being removed.
    """
    out = rgba.copy()
    distance = np.linalg.norm(out[:, :, :3] - NAVY, axis=2)
    weight = np.clip((NAVY_EDGE - distance) / (NAVY_EDGE - NAVY_SOLID), 0.0, 1.0)
    weight = np.where(out[:, :, 3] > 0, weight, 0.0)[:, :, None]
    out[:, :, :3] = out[:, :, :3] * (1.0 - weight) + DARK_MODE_INK * weight
    return out


def _image(rgba: np.ndarray) -> Image.Image:
    return Image.fromarray(np.rint(rgba).astype(np.uint8), mode="RGBA")


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

    The artwork is flat colour with antialiased edges and it arrived carrying
    19,394 distinct colours, almost all of them noise around white. 255 of them
    render the same and store in a fraction of the space. Fast octree because
    it is the only method Pillow will run on an image with an alpha channel,
    and it carries the transparency through itself.
    """
    return image.quantize(colors=255, method=Image.FASTOCTREE, dither=Image.NONE)


def _write(image: Image.Image, path: Path) -> Path:
    _compact(image).save(path, optimize=True)
    return path


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    straight = _unmatte(Image.open(SOURCE))

    written = []
    for suffix, rgba in (("", straight), ("-dark", _for_dark_mode(straight))):
        clean = _trim(_image(rgba))
        lockup = clean.resize(
            (LOCKUP_WIDTH, round(clean.height * LOCKUP_WIDTH / clean.width)),
            Image.LANCZOS,
        )
        written.append(_write(lockup, ASSETS / f"tenuretrack-logo{suffix}.png"))
        written.append(
            _write(
                _square(_split_mark(clean), MARK_SIDE),
                ASSETS / f"tenuretrack-mark{suffix}.png",
            )
        )

    for path in written:
        with Image.open(path) as done:
            print(f"{path.relative_to(ROOT)}  {done.size[0]}x{done.size[1]}  "
                  f"{path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
