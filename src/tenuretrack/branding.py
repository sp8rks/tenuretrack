"""Where the logo lives, for the pages and slides that draw it.

The assets ship inside the package rather than beside it. Colab installs
tenuretrack from GitHub with pip, so a report built there can only reach a file
that came along in the wheel; a path relative to the repository root resolves
to nothing on that machine and the cover page would lose its mark without
saying why.

Every lookup can come back empty, and every caller treats that as normal. A
missing logo is a cosmetic loss. It must never be the reason someone's report
fails to build, so nothing here raises.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["LOGO", "LOGO_DARK", "MARK", "MARK_DARK", "logo_path"]

LOGO = "tenuretrack-logo.png"
"""The full lockup: the graphic over the wordmark. For a cover or a README."""

MARK = "tenuretrack-mark.png"
"""The graphic alone, square. For anywhere the wordmark would be unreadable."""

LOGO_DARK = "tenuretrack-logo-dark.png"
MARK_DARK = "tenuretrack-mark-dark.png"
"""The same two with the artwork's near-black swapped for a light ink.

Half the artwork is a near-black navy: the first half of the wordmark, the
road, the trend line and its dots. On a dark page that half disappears. These
are for surfaces whose background follows the reader's theme, which means the
README and the notebook. The report cover and the deck are drawn on white and
always take the light pair.
"""


def logo_path(name: str = LOGO) -> Path | None:
    """The asset on disk, or None if this install does not carry it.

    `resources.files` rather than a path relative to this module, so an
    installed package finds its own copy wherever pip put it. Anything that
    goes wrong resolving it returns None: an editable install part way through
    a rebuild, a zipped distribution, an asset a packager chose to strip.
    """
    try:
        path = Path(str(resources.files(__package__) / "assets" / name))
    except (TypeError, ValueError, ModuleNotFoundError, OSError):
        return None
    return path if path.is_file() else None
