"""Charts for the deck, and the palette everything drawn here shares.

Kept out of the slide builder so that nothing which only needs a figure has to
import python-pptx, and so the colours have one home. The PDF report draws its
own pages but imports the palette from here, which is what stops the deck and
the report from looking like two different studies.

Style follows `.claude/skills/deck-builder`: one typeface, dark text on white,
one accent colour for the subject, one blue for the cohort, no gradients and no
decoration. A chart here exists to be read at a glance by somebody deciding
whether the cohort is sensible, not to be admired. Type is set several points
larger than the report's, because a deck is read from the back of a room.
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
    "BAND",
    "COHORT",
    "DPI",
    "INK",
    "MUTED",
    "PANEL",
    "RIBBON",
    "RULE",
    "funnel_steps_chart",
    "position_chart",
    "role_pair_chart",
    "trajectory_chart",
    "venue_lead_chart",
]

DPI = 200
INK = "#1a1a1a"
MUTED = "#6a6a6a"
COHORT = "#c7cdd4"
ACCENT = "#c1440e"
"""One accent colour, used only for the subject's own value."""

BAND = "#3b5b7a"
"""The cohort's own colour: medians, funnel steps, top-quartile venues."""

RIBBON = "#dfe4e9"
RULE = "#e2e6ea"
PANEL = "#f5f7f9"
"""Three greys, lightest last: a filled range, a hairline, a tinted panel.

Named here rather than in each consumer so the deck, the PDF and the embedded
figures cannot drift apart. A reader who sees the deck after the report should
not have to work out whether the two are about the same thing.
"""

FONT = {"family": "DejaVu Sans"}


# --------------------------------------------------------------- deck charts
#
# Sized to the box each one lands in, so nothing is letterboxed or squeezed by
# PowerPoint, and set several points larger than the report's figures because a
# deck is read from the back of a room rather than from a lap.


def _deck_axes(width: float, height: float):
    fig = plt.figure(figsize=(width, height))
    fig.patch.set_facecolor("white")
    return fig


def _bare(ax) -> None:
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)


def _tidy_number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def position_chart(
    rows: Sequence[
        tuple[str, float | None, float | None, float | None, float | None, bool, str]
    ],
    path: str | Path,
    *,
    subject_name: str = "This record",
    width: float = 11.9,
    height: float = 4.5,
) -> Path:
    """One row per metric: the cohort's middle half, and where one record falls.

    Every band is drawn the same length whatever the units, so the rows line up
    and the eye reads seven of them at once. The alternative, one panel per
    metric on its own vertical scale, gives no shared baseline and nothing to
    compare across.
    """
    rows = list(rows)
    fig = _deck_axes(width, height)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    left, right = 0.275, 0.685
    label_x, position_x = 0.255, 0.775
    top, bottom = 0.855, 0.115
    step = (top - bottom) / max(len(rows), 1)
    drew_a_marker = False

    for x, align, text in ((left, "left", "cohort p25"), (right, "right", "cohort p75")):
        ax.text(x, top + 0.045, text, ha=align, va="bottom", fontsize=10,
                color=MUTED, **FONT)
    ax.text(position_x, top + 0.045, "where it falls", ha="left", va="bottom",
            fontsize=10, color=MUTED, **FONT)

    for i, (label, value, p25, p50, p75, compared, position) in enumerate(rows):
        y = top - step * (i + 0.5)
        ax.text(label_x, y, label, ha="right", va="center", fontsize=12.5,
                color=INK, **FONT)
        if p25 is None or p75 is None:
            ax.text(left, y, "withheld: too few people to place", ha="left",
                    va="center", fontsize=10, color=MUTED, style="italic", **FONT)
            continue

        ax.plot([left, right], [y, y], color=RIBBON, lw=16,
                solid_capstyle="butt", zorder=1)
        ax.text(left, y + 0.043, _tidy_number(p25), ha="left", va="bottom",
                fontsize=9.5, color=MUTED, **FONT)
        ax.text(right, y + 0.043, _tidy_number(p75), ha="right", va="bottom",
                fontsize=9.5, color=MUTED, **FONT)
        if p50 is not None:
            mid = left + (right - left) * _across(p50, p25, p75)
            ax.plot([mid, mid], [y - 0.036, y + 0.036], color=BAND, lw=3, zorder=2)
            ax.text(mid, y + 0.043, _tidy_number(p50), ha="center", va="bottom",
                    fontsize=9.5, color=BAND, fontweight="bold", **FONT)

        if not compared or value is None:
            ax.text((left + right) / 2, y, _tidy_number(value)
                    + " for this record, shown and not placed",
                    ha="center", va="center", fontsize=10, color=MUTED,
                    style="italic", **FONT)
            continue
        x = left + (right - left) * _across(value, p25, p75)
        ax.plot([x], [y], marker="D", markersize=12, color=ACCENT, zorder=3)
        drew_a_marker = True
        # Beside the diamond, and on whichever side has room. Under it, the
        # label lands on the next row's quartile figures.
        flip = x > (left + right) / 2
        ax.text(x + (-0.012 if flip else 0.012), y, _tidy_number(value),
                ha="right" if flip else "left", va="center", fontsize=11,
                color=ACCENT, fontweight="bold", **FONT)
        ax.text(position_x, y, position, ha="left", va="center", fontsize=10.5,
                color=INK, **FONT)

    handles = [
        plt.Line2D([], [], color=RIBBON, lw=12, label="cohort p25 to p75"),
        plt.Line2D([], [], color=BAND, lw=3, label="cohort median"),
    ]
    # The subject's key appears only when a marker was actually drawn. A legend
    # advertising a diamond the chart does not contain is its own small lie,
    # and on a deck of one metric that diamond is the whole claim.
    if drew_a_marker:
        handles.append(
            plt.Line2D([], [], marker="D", linestyle="none", color=ACCENT,
                       markersize=9, label=subject_name)
        )
    fig.legend(
        handles=handles,
        loc="lower left", bbox_to_anchor=(0.275, 0.0), ncol=len(handles),
        frameon=False, fontsize=10,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def _across(value: float, p25: float, p75: float) -> float:
    """Where a value sits across the band, held just outside it at the ends.

    Clamped tightly, because the words saying where the value falls sit just
    right of the band and a marker allowed to run further lands on them.
    """
    span = p75 - p25
    if span <= 0:
        return 0.5
    return min(max((value - p25) / span, -0.09), 1.09)


def trajectory_chart(
    series: Sequence[
        tuple[
            str, Sequence[int], Sequence[float], Sequence[float],
            Sequence[float], float | None, bool,
        ]
    ],
    subject_name: str,
    horizon: int,
    path: str | Path,
    *,
    width: float = 11.9,
    height: float = 4.3,
) -> Path:
    """Small multiples of the cohort's middle half across the clock.

    `series` is (label, years, p25, p50, p75, subject value or None, is a share).
    """
    series = list(series)
    columns = min(3, len(series))
    rows_n = -(-len(series) // columns)
    fig = _deck_axes(width, height)

    left, right, top, bottom = 0.055, 0.985, 0.90, 0.215
    h_gap, v_gap = 0.085, 0.185
    panel_w = (right - left - h_gap * (columns - 1)) / columns
    panel_h = (top - bottom - v_gap * (rows_n - 1)) / rows_n

    for i, (label, years, p25, p50, p75, value, is_share) in enumerate(series):
        col, row = i % columns, i // columns
        ax = fig.add_axes([
            left + col * (panel_w + h_gap),
            top - panel_h - row * (panel_h + v_gap),
            panel_w, panel_h,
        ])
        ax.set_facecolor("white")
        ax.fill_between(years, p25, p75, color=RIBBON, linewidth=0, zorder=1)
        ax.plot(years, p50, color=BAND, lw=2.8, zorder=2)
        highest = max(list(p75) + [0.0])
        if value is not None:
            ax.plot([horizon], [value], marker="D", markersize=11, color=ACCENT,
                    zorder=4)
            highest = max(highest, value)
        ax.set_ylim(0, highest * 1.26 if highest else 1.0)
        ax.set_xlim(min(years) - 0.3, max(years) + 0.3)
        ax.set_xticks(list(years))
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(RULE)
        ax.tick_params(colors=MUTED, labelsize=9.5, length=2)
        if is_share:
            ax.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
        ax.set_title(textwrap.fill(label, 24), fontsize=12, color=INK, pad=8,
                     **FONT)
        if row == rows_n - 1:
            ax.set_xlabel("career year", fontsize=9.5, color=MUTED, labelpad=3,
                          **FONT)

    fig.legend(
        handles=[
            plt.Line2D([], [], color=RIBBON, lw=12, label="cohort p25 to p75"),
            plt.Line2D([], [], color=BAND, lw=2.8, label="cohort median"),
            plt.Line2D([], [], marker="D", linestyle="none", color=ACCENT,
                       markersize=9,
                       label=f"{subject_name}, at year {horizon}"),
        ],
        loc="lower left", bbox_to_anchor=(0.055, 0.005), ncol=3, frameon=False,
        fontsize=10,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def funnel_steps_chart(
    steps: Sequence[tuple[str, int]],
    path: str | Path,
    *,
    width: float = 7.6,
    height: float = 4.6,
) -> Path:
    """The funnel on a log axis, each step carrying what it kept.

    A linear axis gives the opening step the whole width and every step after
    it a stub, which hides the filters a reader needs in order to judge whether
    the cohort answers their question.
    """
    steps = list(steps)
    labels = [label for label, _ in steps]
    kept = [max(value, 1) for _, value in steps]
    shares = [1.0] + [
        kept[i] / kept[i - 1] if kept[i - 1] else 0.0 for i in range(1, len(kept))
    ]

    fig = _deck_axes(width, height)
    ax = fig.add_axes([0.30, 0.09, 0.68, 0.88])
    ax.set_facecolor("white")
    positions = range(len(kept))
    ax.barh(positions, kept, color=BAND, height=0.55, zorder=2)
    ax.set_yticks(list(positions))
    ax.set_yticklabels([textwrap.fill(t, 22) for t in labels], fontsize=11,
                       color=INK, **FONT)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(1, max(kept) * 6.0)
    _bare(ax)
    ax.tick_params(axis="x", which="both", labelbottom=False, length=0)
    ax.grid(axis="x", color=RULE, linewidth=0.9)
    ax.set_axisbelow(True)

    for i, (value, share) in enumerate(zip(kept, shares, strict=True)):
        ax.text(value * 1.18, i - 0.14, f"{value:,}", va="center", fontsize=12,
                color=INK, fontweight="bold", **FONT)
        if i:
            ax.text(value * 1.18, i + 0.24, f"kept {share:.0%}", va="center",
                    fontsize=9.5, color=MUTED, **FONT)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def venue_lead_chart(
    venues: Sequence[tuple[str, int, float | None, bool]],
    lead_shares: dict,
    path: str | Path,
    *,
    horizon: int = 6,
    width: float = 11.9,
    height: float = 4.4,
) -> Path:
    """The busiest venues, and how much of the work in each the cohort led."""
    venues = list(venues)
    names = [
        name if impact is None else f"{name}  ({impact:.1f})"
        for name, _c, impact, _q in venues
    ]
    counts = [count for _n, count, _i, _q in venues]
    colours = [BAND if top else COHORT for _n, _c, _i, top in venues]

    fig = _deck_axes(width, height)
    paired = bool(lead_shares)
    ax = fig.add_axes([0.30, 0.16, 0.44 if paired else 0.67, 0.78])
    ax.set_facecolor("white")
    positions = range(len(counts))
    ax.barh(positions, counts, color=colours, height=0.66)
    ax.set_yticks(list(positions))
    ax.set_yticklabels([textwrap.fill(n, 32) for n in names], fontsize=10,
                       color=INK, **FONT)
    ax.invert_yaxis()
    _bare(ax)
    ax.set_xlim(0, max(counts) * 1.18)
    ax.tick_params(axis="x", labelbottom=False)
    ax.set_xlabel(f"cohort papers through year {horizon}", fontsize=10,
                  color=MUTED, labelpad=6, **FONT)
    for i, value in enumerate(counts):
        ax.text(value + max(counts) * 0.02, i, f"{value:,}", va="center",
                fontsize=10, color=INK, fontweight="bold", **FONT)

    if paired:
        ax2 = fig.add_axes([0.78, 0.16, 0.20, 0.78])
        ax2.set_facecolor("white")
        shares = [lead_shares.get(name, 0.0) for name, _c, _i, _q in venues]
        widest = max(shares + [0.01])
        ax2.barh(positions, shares, color=ACCENT, height=0.66, alpha=0.85)
        ax2.set_yticks(list(positions))
        ax2.set_yticklabels([])
        ax2.invert_yaxis()
        _bare(ax2)
        ax2.set_xlim(0, widest * 1.42)
        ax2.tick_params(labelbottom=False)
        ax2.set_xlabel("share the cohort led", fontsize=10, color=MUTED,
                       labelpad=6, **FONT)
        for i, value in enumerate(shares):
            ax2.text(value + widest * 0.05, i, f"{value:.0%}", va="center",
                     fontsize=10, color=INK, **FONT)

    fig.legend(
        handles=[
            plt.Line2D([], [], color=BAND, lw=11,
                       label="top quartile in this cohort"),
            plt.Line2D([], [], color=COHORT, lw=11, label="every other venue"),
        ],
        loc="lower left", bbox_to_anchor=(0.30, 0.0), ncol=2, frameon=False,
        fontsize=10,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path


def role_pair_chart(
    pooled: Sequence[tuple[str, float | None, int]],
    paired: tuple[float, float, int] | None,
    path: str | Path,
    *,
    width: float = 11.9,
    height: float = 3.9,
) -> Path:
    """Two readings of the same question, side by side because they can disagree.

    `pooled` is (label, rate, papers) per role; `paired` is the two within-person
    medians and how many people they cover.
    """
    pooled = list(pooled)
    fig = _deck_axes(width, height)

    ax = fig.add_axes([0.06, 0.17, 0.38, 0.66])
    ax.set_facecolor("white")
    values = [rate or 0.0 for _l, rate, _p in pooled]
    headroom = max(values + [0.01])
    colours = [ACCENT if label.startswith("Led") else COHORT
               for label, _r, _p in pooled]
    ax.bar(range(len(values)), values, color=colours, width=0.6)
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels([textwrap.fill(label, 13) for label, _r, _p in pooled],
                       fontsize=11, color=INK, **FONT)
    ax.set_ylim(0, headroom * 1.36)
    ax.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=10)
    for i, ((_label, _rate, papers), value) in enumerate(
        zip(pooled, values, strict=True)
    ):
        ax.text(i, value + headroom * 0.04, f"{value:.1%}", ha="center",
                fontsize=13, color=INK, fontweight="bold", **FONT)
        if papers:
            ax.text(i, value + headroom * 0.155, f"{papers:,} papers",
                    ha="center", fontsize=9, color=MUTED, **FONT)
    ax.set_title("Across every paper the cohort wrote", fontsize=12.5,
                 color=INK, pad=12, **FONT)

    if paired:
        led, middle, people = paired
        ax2 = fig.add_axes([0.58, 0.17, 0.36, 0.66])
        ax2.set_facecolor("white")
        pair_top = max(led, middle)
        ax2.bar([0, 1], [led, middle], color=[ACCENT, COHORT], width=0.5)
        ax2.set_xticks([0, 1])
        ax2.set_xticklabels(["papers they led", "papers they did not lead"],
                            fontsize=11, color=INK, **FONT)
        ax2.set_ylim(0, pair_top * 1.36)
        ax2.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
        for side in ("top", "right"):
            ax2.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax2.spines[side].set_color(RULE)
        ax2.tick_params(colors=MUTED, labelsize=10)
        for x, value in ((0, led), (1, middle)):
            ax2.text(x, value + pair_top * 0.04, f"{value:.1%}", ha="center",
                     fontsize=13, color=INK, fontweight="bold", **FONT)
        ax2.set_title(f"The same {people:,} people, each their own comparison",
                      fontsize=12.5, color=INK, pad=12, **FONT)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return path
