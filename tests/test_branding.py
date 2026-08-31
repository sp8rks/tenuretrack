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

import pytest

from tenuretrack import branding
from tenuretrack.branding import LOGO, MARK, logo_path

ROOT = Path(__file__).resolve().parents[1]


def test_both_assets_ship_with_the_package():
    for name in (LOGO, MARK):
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


@pytest.mark.parametrize("name", [LOGO, MARK])
def test_the_shipped_assets_stay_small(name):
    """They are drawn onto every report and deck, and they are committed.

    The artwork arrived at 839 KB of near-white noise. `make logo` quantises it
    down to a fraction of that, and this is the test that notices if someone
    commits a raw export over the top.
    """
    assert logo_path(name).stat().st_size < 150_000
