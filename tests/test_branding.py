"""The logo is an asset the build depends on, so it gets the same treatment.

Two things can go wrong with it and neither one announces itself. The file can
fail to travel into the wheel, in which case the Colab path, which is the path
most people take, builds a report with a hole where the mark was. And a missing
file can be allowed to raise, in which case a cosmetic asset becomes the reason
somebody's run dies at the last step.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tenuretrack import branding
from tenuretrack.branding import LOGO, LOGO_DARK, MARK, MARK_DARK, logo_path

ROOT = Path(__file__).resolve().parents[1]

ALL_ASSETS = (LOGO, MARK, LOGO_DARK, MARK_DARK)


def test_every_asset_ships_with_the_package():
    for name in ALL_ASSETS:
        path = logo_path(name)
        assert path is not None, f"{name} is not installed with the package"
        assert path.is_file()
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_assets_live_inside_the_package_not_beside_it():
    """A path relative to the repository root resolves to nothing on Colab.

    Colab pip-installs tenuretrack from GitHub. Only what setuptools packaged
    exists on that machine, so the assets have to sit under `src/tenuretrack/`
    and the wheel has to be told to carry them.
    """
    assert logo_path().parent == ROOT / "src" / "tenuretrack" / "assets"

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["tenuretrack"]
    assert any(pattern.startswith("assets/") for pattern in patterns)


def test_a_missing_asset_is_none_and_never_an_exception():
    """Every caller treats the logo as optional, so this has to return, not raise."""
    assert logo_path("no-such-file.png") is None


def test_the_report_and_the_deck_survive_without_it(monkeypatch):
    """The whole point of returning None: a cosmetic asset cannot break a run."""
    monkeypatch.setattr(branding, "logo_path", lambda name=LOGO: None)
    assert branding.logo_path() is None


def test_the_source_artwork_is_not_packaged():
    """It is 839 KB and nothing at runtime reads it, so it stays out of the wheel."""
    source = ROOT / "assets" / "tenuretrack-logo-source.png"
    assert source.is_file(), "the master artwork should stay in the repository"
    assert logo_path("tenuretrack-logo-source.png") is None


@pytest.mark.parametrize("name", ALL_ASSETS)
def test_the_shipped_assets_stay_small(name):
    """They are drawn onto every report and deck, and they are committed.

    The artwork arrived at 839 KB of near-white noise. `make logo` quantises it
    down to a fraction of that, and this is the test that notices if someone
    commits a raw export over the top.
    """
    assert logo_path(name).stat().st_size < 150_000


# ------------------------------------------------------- light and dark themes


def _pixels(name: str) -> np.ndarray:
    return np.asarray(Image.open(logo_path(name)).convert("RGBA"), dtype=float)


def _luminance(pixels: np.ndarray) -> np.ndarray:
    return pixels[:, :, :3] @ [0.299, 0.587, 0.114]


@pytest.mark.parametrize("name", [LOGO, MARK])
def test_no_opaque_white_survives_in_the_light_pair(name):
    """The bug a white page hides and a dark page shows.

    Flooding the background in from the corners left every antialiased edge
    pixel fully opaque, so the artwork wore a white halo, and the flood could
    not reach the white enclosed by the letters, so each `e` and `a` carried a
    white blob. Both are invisible against white and obvious against #0d1117.
    The fix is to treat white as the matte it is and recover coverage from it.
    This is the assertion that says it stayed fixed.

    The dark pair is light ink by design and is checked on its own below.
    """
    pixels = _pixels(name)
    opaque_white = (pixels[:, :, 3] > 200) & (_luminance(pixels) > 235)
    assert opaque_white.sum() == 0, (
        f"{name} carries {int(opaque_white.sum())} opaque near-white pixels, "
        "which will read as halos and blobs on a dark background"
    )


@pytest.mark.parametrize(
    ("light", "dark"), [(LOGO, LOGO_DARK), (MARK, MARK_DARK)]
)
def test_the_dark_variant_lightens_the_ink_that_would_vanish(light, dark):
    """Half the artwork is a near-black navy, and a dark page swallows it.

    Compares the mean luminance of the opaque pixels in each. The dark
    variant has to be substantially lighter, or it is the light one under
    another name and the README fix does nothing.
    """

    def mean_ink_luminance(name: str) -> float:
        pixels = _pixels(name)
        return float(np.mean(_luminance(pixels)[pixels[:, :, 3] > 200]))

    assert mean_ink_luminance(dark) > mean_ink_luminance(light) + 40


@pytest.mark.parametrize("name", [LOGO_DARK, MARK_DARK])
def test_the_dark_variant_keeps_the_road_markings_open(name):
    """The dashes and the letter counters are holes, not white paint.

    That is what lets one drawing work on both themes: on a light page the
    holes show white and on a dark page they show dark. If they were ever
    filled in, the dark variant would be a light road with invisible
    markings and letters with solid middles.
    """
    pixels = _pixels(name)
    assert (pixels[:, :, 3] < 20).any(), f"{name} has no transparent pixels at all"


def test_the_readme_offers_both_to_the_browser():
    """A plain <img> is what put a near-black wordmark on a near-black page."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in readme
    assert LOGO_DARK in readme
    assert LOGO in readme


def test_the_notebook_offers_both_to_the_browser():
    notebook = (ROOT / "notebooks" / "tenuretrack_colab.ipynb").read_text(
        encoding="utf-8"
    )
    assert "prefers-color-scheme: dark" in notebook
    assert LOGO_DARK in notebook
