"""Charts for the deck and the report.

Kept separate from the slide builder so the Markdown report can embed the same
PNGs, which is the only way a figure and a table can be guaranteed to agree:
they are the same numbers, read once.

Style follows `.claude/skills/deck-builder`: one typeface, dark text on white,
a single accent colour for the subject, no gradients and no decoration. A chart
in this deck exists to be read at a glance by somebody deciding whether the
cohort is sensible, not to be admired.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in a notebook, a container, or CI
import matplotlib.pyplot as plt  # noqa: E402

__all__ = [
    "ACCENT",
    "COHORT",
    "DPI",
    "INK",
    "MUTED",
    "dot_and_range_chart",
    "panel_range_chart",
    "funnel_chart",
    "role_rate_chart",
    "venue_chart",
]

DPI = 200
INK = "#1a1a1a"
MUTED = "#8a8a8a"
COHORT = "#c7cdd4"
ACCENT = "#c1440e"
"""One accent colour, used only for the subject's own value."""

FONT = {"family": "DejaVu Sans"}


def _figure(width: float, height: float):
    fig, ax = plt.subplots(figsize=(width, height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=9)
    return fig, ax


def _save(fig, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def funnel_chart(
    steps: Sequence[tuple[str, int]], path: str | Path, *, width=9.0, height=4.0
) -> Path:
    """The cohort funnel as horizontal bars, widest at the top.

    This is the chart a reader should look at first: if one filter removed
    almost everybody, the cohort is answering a different question.
    """
    labels = [label for label, _ in steps][::-1]
    values = [value for _, value in steps][::-1]

    fig, ax = _figure(width, height)
    bars = ax.barh(labels, values, color=COHORT, edgecolor="none")
    largest = max(values) if values else 1
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + largest * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            va="center",
            fontsize=9,
            color=INK,
        )
    ax.set_xlim(0, largest * 1.15)
    ax.set_xlabel("People remaining", fontsize=9, color=INK)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    return _save(fig, path)


def dot_and_range_chart(
    rows: Sequence[tuple[str, float | None, float | None, float | None, float | None, bool]],
    path: str | Path,
    *,
    subject_name: str = "This record",
    width=9.0,
    height=4.5,
) -> Path:
    """Cohort p25 to p75 as a band with a median tick, the subject as a dot.

    Each metric is drawn on its own scale, because publications and lead share
    do not share units. The point is where the dot sits inside the band, not
    how far along the axis it is.

    Metrics that are reported but not compared, meaning citations, get neither
    a band nor a dot, only the words. A dot anywhere on this axis would read as
    a position, and a dot in the middle would read as "at the median", which is
    the one thing the citation row must not say.
    """
    rows = list(rows)
    fig, ax = _figure(width, height)
    positions = range(len(rows))
    drew_a_dot = False

    for y, (_label, value, p25, p50, p75, compared) in zip(positions, rows, strict=True):
        placeable = compared and p25 is not None and p75 is not None
        if not placeable:
            # No band and, deliberately, no dot. Drawing the dot anywhere on
            # this axis would read as a position, and the citation row exists
            # precisely because there is no position to show.
            ax.text(
                0.5,
                y,
                "reported, not compared",
                ha="center",
                va="center",
                fontsize=9,
                color=MUTED,
                style="italic",
            )
            continue

        span = max(p75 - p25, 1e-9)
        ax.plot([0.0, 1.0], [y, y], color=COHORT, linewidth=9, solid_capstyle="butt")
        if p50 is not None:
            ax.plot(
                [(p50 - p25) / span] * 2, [y - 0.22, y + 0.22], color=MUTED, linewidth=2
            )
        if value is not None:
            # Clamped, so a value far outside the band reads as "past p75"
            # rather than stretching every other row off the chart.
            x = min(max((value - p25) / span, -0.08), 1.08)
            ax.plot([x], [y], marker="o", markersize=9, color=ACCENT, zorder=3)
            drew_a_dot = True

    ax.set_yticks(list(positions))
    ax.set_yticklabels([label for label, *_ in rows], fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(-0.2, 1.2)
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xticklabels(["cohort p25", "median", "cohort p75"], fontsize=9, color=MUTED)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    # The subject's key appears only when a dot was actually drawn: a legend
    # advertising a marker the chart does not contain is its own small lie.
    handles = [plt.Line2D([], [], color=COHORT, linewidth=9, label="cohort p25 to p75")]
    if drew_a_dot:
        handles.append(
            plt.Line2D(
                [], [], marker="o", linestyle="none", color=ACCENT, label=subject_name
            )
        )
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=len(handles),
        frameon=False,
        fontsize=9,
    )
    return _save(fig, path)


def venue_chart(
    venues: Sequence[tuple[str, int, float | None, bool]],
    path: str | Path,
    *,
    width=6.5,
    height=5.0,
) -> Path:
    """The cohort's busiest venues, top-quartile ones in the accent colour."""
    venues = list(venues)[::-1]
    labels = [name if len(name) <= 38 else name[:36] + ".." for name, *_ in venues]
    counts = [count for _, count, _, _ in venues]
    colors = [ACCENT if is_top else COHORT for *_, is_top in venues]

    fig, ax = _figure(width, height)
    ax.barh(labels, counts, color=colors, edgecolor="none")
    ax.set_xlabel("Cohort papers in the window", fontsize=9, color=INK)
    ax.legend(
        handles=[
            plt.Line2D([], [], color=ACCENT, linewidth=9, label="top-quartile venue"),
            plt.Line2D([], [], color=COHORT, linewidth=9, label="other"),
        ],
        loc="lower right",
        frameon=False,
        fontsize=8,
    )
    return _save(fig, path)


def role_rate_chart(
    rates: Sequence[tuple[str, float | None]], path: str | Path, *, width=4.5, height=3.2
) -> Path:
    """Top-quartile venue rate by authorship role."""
    labels = [label for label, _ in rates]
    values = [0.0 if rate is None else rate for _, rate in rates]

    fig, ax = _figure(width, height)
    bars = ax.bar(labels, values, color=COHORT, edgecolor="none", width=0.6)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.005,
            f"{value:.0%}",
            ha="center",
            fontsize=9,
            color=INK,
        )
    ax.set_ylim(0, max(values + [0.01]) * 1.25)
    ax.set_ylabel("Papers in top-quartile venues", fontsize=9, color=INK)
    ax.tick_params(axis="x", labelsize=8)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    return _save(fig, path)


def panel_range_chart(
    panels: Sequence[tuple[str, float | None, float, float, float]],
    subject_name: str,
    horizon: int,
    path: str | Path,
    *,
    width: float = 12.0,
    height: float = 3.8,
):
    """One small panel per metric: the cohort's middle half, and the subject in it.

    `panels` is (label, subject value, p25, p50, p75). The subject's value may
    be None, for a metric that is reported and not compared.

    The band-and-diamond shape repeats across metrics on their own scales,
    which is what lets someone read several different units at a glance.
    `dot_and_range_chart` puts every metric on one normalised axis instead,
    which is denser but hides the actual numbers. The deck wants the compact
    one; the PDF has room for the one that shows its working.
    """
    panels = list(panels)
    if not panels:
        raise ValueError("panel_range_chart needs at least one panel")

    short = subject_name.split()[0] if subject_name.split() else subject_name

    fig, axes = plt.subplots(1, len(panels), figsize=(width, height))
    if len(panels) == 1:
        axes = [axes]
    fig.patch.set_facecolor("white")

    for ax, (label, value, p25, p50, p75) in zip(axes, panels, strict=True):
        ax.set_facecolor("white")
        for side in ("top", "right", "bottom"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(MUTED)
        ax.tick_params(colors=INK, labelsize=8, bottom=False, labelbottom=False)
        ax.set_xlim(0, 1)

        ax.axhspan(p25, p75, xmin=0.30, xmax=0.88, color=COHORT, zorder=1)
        ax.plot([0.30, 0.88], [p50, p50], color="#3b5b7a", lw=2.4, zorder=2)

        top = max([p75, value if value is not None else p75]) or 1.0
        ax.set_ylim(0, top * 1.30)

        for y, text in (
            (p75, "p75 " + _tidy(p75)),
            (p50, "median " + _tidy(p50)),
            (p25, "p25 " + _tidy(p25)),
        ):
            ax.text(0.28, y, text, ha="right", va="center", fontsize=7.5,
                    color=MUTED, **FONT)

        if value is not None:
            ax.plot([0.59], [value], marker="D", markersize=9, color=ACCENT, zorder=3)
            ax.text(0.65, value, short + ": " + _tidy(value), ha="left",
                    va="center", fontsize=8.5, color=ACCENT, fontweight="bold", **FONT)
        else:
            # Above the band, where it cannot land on the median label.
            ax.text(0.59, top * 1.18, "reported," + chr(10) + "not compared",
                    ha="center", va="center", fontsize=7.5, color=MUTED,
                    style="italic", **FONT)

        ax.set_title(textwrap.fill(label, 26), fontsize=9.5, color=INK, pad=10, **FONT)

    fig.suptitle(
        "Cohort middle half (shaded, median line) and " + short
        + ", both through career year " + str(horizon),
        fontsize=11, color=INK, **FONT,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def _tidy(value: float) -> str:
    """Numbers as a reader writes them: no trailing zeros on a whole count."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
