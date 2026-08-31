"""A standalone PDF of the whole report, built without LibreOffice.

`slides.export_pdf` converts the deck by shelling out to LibreOffice, which is
not on a Colab machine and is a several-minute install. The no-install path is
the one most people use, so the PDF they get at the end cannot depend on it.
This module draws the pages directly with matplotlib, which is already a
dependency because the figures need it.

It reads the pipeline's own output files and recomputes nothing, for the same
reason `slides.py` does: a figure and a table that disagree are worse than
either one alone.

The page order follows the order a reader needs the answers in. Where does this
record sit, how did the subfield get there year by year, what are the numbers
underneath, who is in the cohort, where does the subfield publish, who leads the
papers that reach the best venues, and what none of it can see.

Aggregates only, like everything under `results/`. The one name on these pages
is the subject's, and it is there because they ran the tool on themselves.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from tenuretrack.chaperone import CHAPERONE_CSV  # noqa: E402
from tenuretrack.config import Config  # noqa: E402
from tenuretrack.figures import ACCENT, COHORT, INK, MUTED  # noqa: E402
from tenuretrack.guardrail import assert_aggregates_only  # noqa: E402
from tenuretrack.metrics import BENCHMARKS_CSV, METRICS  # noqa: E402
from tenuretrack.pool import FUNNEL_FILENAME  # noqa: E402
from tenuretrack.report import SUBJECT_CSV, VENUES_CSV  # noqa: E402
from tenuretrack.slide_data import SlideData, load_slide_data  # noqa: E402

__all__ = ["PDF_FILENAME", "build_pdf_report"]

PDF_FILENAME = "report.pdf"

PAGE = (11.0, 8.5)
"""US letter, landscape, so the wide comparison panels are not cramped."""

FONT = {"family": "DejaVu Sans"}
BAND = "#3b5b7a"
RIBBON = "#dfe4e9"
RULE = "#e2e6ea"
PANEL = "#f5f7f9"

METRIC_ORDER = tuple(metric.key for metric in METRICS)
METRIC_LABELS = {metric.key: metric.label for metric in METRICS}
SHARE_METRICS = frozenset(m.key for m in METRICS if m.is_share)

SHORT_LABELS = {
    "pubs": "Journal articles",
    "led": "Articles led",
    "lead_share": "Share led",
    "citations": "Citations",
    "h_index": "h-index",
    "venue_impact_median": "Median venue impact",
    "top_quartile_share": "Top-quartile venue share",
}
"""Chart-sized versions of the table labels, for axes that have no room."""

TRAJECTORY_METRICS = (
    "pubs",
    "led",
    "h_index",
    "lead_share",
    "top_quartile_share",
    "citations",
)


# ----------------------------------------------------------------- page frame


def _page():
    fig = plt.figure(figsize=PAGE)
    fig.patch.set_facecolor("white")
    return fig


def _close(pdf: PdfPages, fig) -> None:
    pdf.savefig(fig, facecolor="white")
    plt.close(fig)


def _title(fig, text: str, kicker: str | None = None) -> None:
    """A page heading, with an optional line above it saying which section this is."""
    if kicker:
        fig.text(
            0.06, 0.955, kicker.upper(), fontsize=8.5, color=ACCENT,
            fontweight="bold", va="top", **FONT,
        )
    fig.text(0.06, 0.925, text, fontsize=20, color=INK, fontweight="bold",
             va="top", **FONT)
    fig.add_artist(plt.Line2D([0.06, 0.16], [0.882, 0.882], color=ACCENT, lw=3))


def _body(fig, text: str, y: float, size: float = 10.5, width: int = 108,
          color: str = INK, x: float = 0.06, gap: float = 0.028) -> float:
    """Draw a wrapped paragraph and return the y the next one should start at."""
    wrapped = textwrap.fill(text, width)
    lines = wrapped.count("\n") + 1
    fig.text(x, y, wrapped, fontsize=size, color=color, va="top",
             linespacing=1.5, **FONT)
    return y - (lines * size * 0.0028) - gap


def _lede(fig, text: str, y: float = 0.855, width: int = 118) -> float:
    """One sentence under the heading saying what the reader is looking at."""
    return _body(fig, text, y, size=11, width=width, color=MUTED)


def _footnote(fig, text: str, width: int = 132) -> None:
    """The small print, always in the same place so a reader learns where it is.

    Anchored to the bottom of the page rather than to a fixed top, so a note
    that runs to four lines grows upward into the white space instead of off
    the end of the paper.
    """
    fig.text(0.06, 0.045, textwrap.fill(text, width), fontsize=8.5, color=MUTED,
             va="bottom", linespacing=1.5, **FONT)


def _tidy(value) -> str:
    """Numbers as a reader writes them: no trailing zeros on a whole count."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cell(row, quartile: str) -> str:
    """One quartile with its confidence interval, as the table shows it."""
    low = _tidy(row.get(quartile + "_ci_low"))
    high = _tidy(row.get(quartile + "_ci_high"))
    if not low or not high:
        return _tidy(row.get(quartile))
    return f"{_tidy(row.get(quartile))}   ({low} to {high})"


def _ordered(rows):
    return sorted(
        rows,
        key=lambda r: METRIC_ORDER.index(r["metric"])
        if r["metric"] in METRIC_ORDER
        else 99,
    )


def _stat_tiles(fig, tiles, *, y: float, height: float = 0.115) -> None:
    """A row of headline numbers, each with the word for what it counts."""
    left, right = 0.06, 0.94
    gap = 0.018
    slot = (right - left + gap) / len(tiles) - gap
    for i, (number, caption) in enumerate(tiles):
        x = left + i * (slot + gap)
        fig.add_artist(
            FancyBboxPatch(
                (x, y), slot, height,
                boxstyle="round,pad=0,rounding_size=0.008",
                linewidth=0, facecolor=PANEL, transform=fig.transFigure,
                figure=fig, zorder=0,
            )
        )
        fig.text(x + 0.018, y + height - 0.028, number,
                 fontsize=21 if len(number) <= 7 else 16, color=INK,
                 fontweight="bold", va="top", **FONT)
        fig.text(x + 0.018, y + 0.022, textwrap.fill(caption, 26), fontsize=8.5,
                 color=MUTED, va="bottom", linespacing=1.4, **FONT)


# ----------------------------------------------------------------------- pages


def _cover(pdf: PdfPages, data: SlideData) -> None:
    fig = _page()
    subject = data.config.subject
    label = data.config.subfield.label or "the subfield"

    fig.text(0.06, 0.90, "PUBLICATION NORMS THROUGH THE TENURE CLOCK",
             fontsize=9, color=ACCENT, fontweight="bold", va="top", **FONT)
    fig.text(0.06, 0.855, subject.name, fontsize=32, color=INK,
             fontweight="bold", va="top", **FONT)
    fig.text(0.06, 0.788, f"{label}, at career year {data.horizon}",
             fontsize=17, color=MUTED, va="top", **FONT)
    fig.add_artist(plt.Line2D([0.06, 0.30], [0.735, 0.735], color=ACCENT, lw=4))

    _stat_tiles(
        fig,
        [
            (f"{data.cohort_size:,}", "people in the cohort"),
            (str(data.horizon), "career year both sides are measured at"),
            (f"{data.config.cohort.start_window[0]} to "
             f"{data.config.cohort.start_window[1]}", "when the cohort started"),
            (str(len(data.config.subfield.topics)),
             "OpenAlex topics defining the subfield"),
        ],
        y=0.600,
    )

    y = 0.535
    y = _body(
        fig,
        f"{subject.name} started a tenure-line appointment at "
        f"{subject.institution_name} in {subject.start_year}. Everyone in the "
        "cohort is estimated to have started one in "
        f"{label} between {data.config.cohort.start_window[0]} and "
        f"{data.config.cohort.start_window[1]}, so both sides can be read at the "
        f"same point on the clock. {subject.name} is not in the cohort.",
        y, size=11.5, width=112,
    )
    y = _body(
        fig,
        "These numbers describe what a group of people did. They are not a "
        "standard, nobody in the cohort agreed to be measured, and no part of "
        "this says what any one career should look like.",
        y, size=11.5, width=112,
    )

    contents = [
        ("Where this record sits", "each measure against the cohort's middle half"),
        ("Year by year", "how the cohort's record grew across the clock"),
        ("The numbers", "quartiles, with confidence intervals"),
        ("Who is in the cohort", "every filter, and how many people it left"),
        ("Where the subfield publishes", "which journals top quartile covers"),
    ]
    if data.has_chaperone:
        contents.append(
            ("Who leads the good papers",
             "led against co-authored, within the same people")
        )
    contents.append(("What this cannot see", "the limits, in plain words"))

    fig.text(0.06, y - 0.005, "WHAT IS IN HERE", fontsize=8.5, color=MUTED,
             fontweight="bold", va="top", **FONT)
    row_y = y - 0.048
    spacing = min(0.033, max((row_y - 0.135) / len(contents), 0.024))
    for i, (heading, gloss) in enumerate(contents, start=1):
        fig.text(0.065, row_y, str(i), fontsize=9.5, color=ACCENT,
                 fontweight="bold", va="center", **FONT)
        fig.text(0.10, row_y, heading, fontsize=10.5, color=INK, va="center", **FONT)
        fig.text(0.34, row_y, gloss, fontsize=9.5, color=MUTED, va="center", **FONT)
        row_y -= spacing

    _footnote(
        fig,
        "Aggregates only. No cohort member is named anywhere in this document. "
        "Built with tenuretrack from OpenAlex data (Priem, Piwowar and Orr, "
        "2022), CC0. The method in full is in docs/methods.md.",
    )
    _close(pdf, fig)


def _place(value: float, p25: float, p75: float) -> float:
    """Where a value sits across the band, clamped just outside it at the ends."""
    span = p75 - p25
    if span <= 0:
        return 0.5
    return min(max((value - p25) / span, -0.12), 1.12)


def _subject_page(pdf: PdfPages, data: SlideData) -> None:
    """Every measure as one row: the cohort's middle half, and where this record falls.

    Rows, where this page used to carry a column of panels. Each panel floated
    on its own vertical scale, so nothing lined up and the eye had no way to
    read six of them together. On rows every band starts and ends in the same
    place, the numbers sit at the ends where they can be read, and how far
    along the row the diamond falls is the whole message.
    """
    if not data.subject:
        return
    rows = _ordered(data.subject)
    if not rows:
        return

    fig = _page()
    _title(fig, f"Where this record sits at year {data.horizon}",
           kicker="1. Against the cohort")
    _lede(
        fig,
        "The shaded band is the middle half of the cohort, p25 to p75, with the "
        f"median marked. The diamond is {data.config.subject.name}. Both sides "
        f"are counted through career year {data.horizon}.",
    )

    left, right = 0.30, 0.68
    label_x, position_x = 0.275, 0.745
    top, bottom = 0.775, 0.175
    step = (top - bottom) / max(len(rows), 1)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    for x, align, text in ((left, "left", "cohort p25"),
                           (right, "right", "cohort p75")):
        ax.text(x, top + 0.020, text, ha=align, va="bottom", fontsize=8.5,
                color=MUTED, **FONT)
    ax.text(position_x, top + 0.020, "where it falls", ha="left", va="bottom",
            fontsize=8.5, color=MUTED, **FONT)

    for i, row in enumerate(rows):
        y = top - step * (i + 0.5)
        label = SHORT_LABELS.get(row["metric"], row.get("label", row["metric"]))
        ax.text(label_x, y, label, ha="right", va="center", fontsize=10.5,
                color=INK, **FONT)

        p25, p50, p75 = (_float(row.get(k)) for k in
                         ("cohort_p25", "cohort_p50", "cohort_p75"))
        value = _float(row.get("value"))
        if p25 is None or p75 is None:
            ax.text(left, y, "withheld: too few people to show a quartile",
                    ha="left", va="center", fontsize=9, color=MUTED,
                    style="italic", **FONT)
            continue

        ax.plot([left, right], [y, y], color=RIBBON, lw=13,
                solid_capstyle="butt", zorder=1)
        ax.text(left, y + 0.024, _tidy(p25), ha="left", va="bottom",
                fontsize=8, color=MUTED, **FONT)
        ax.text(right, y + 0.024, _tidy(p75), ha="right", va="bottom",
                fontsize=8, color=MUTED, **FONT)
        if p50 is not None:
            mid = left + (right - left) * _place(p50, p25, p75)
            ax.plot([mid, mid], [y - 0.018, y + 0.018], color=BAND, lw=2.4, zorder=2)
            ax.text(mid, y + 0.024, _tidy(p50), ha="center", va="bottom",
                    fontsize=8, color=BAND, fontweight="bold", **FONT)

        compared = row.get("compared") == "yes"
        if not compared or value is None:
            ax.text((left + right) / 2, y - 0.022,
                    f"{_tidy(value)} for this record, shown and not placed",
                    ha="center", va="top", fontsize=8.5, color=MUTED,
                    style="italic", **FONT)
            continue

        x = left + (right - left) * _place(value, p25, p75)
        ax.plot([x], [y], marker="D", markersize=9, color=ACCENT, zorder=3)
        ax.text(x, y - 0.022, _tidy(value), ha="center", va="top", fontsize=9,
                color=ACCENT, fontweight="bold", **FONT)
        ax.text(position_x, y, row.get("position", ""), ha="left", va="center",
                fontsize=9, color=INK, **FONT)

    _footnote(
        fig,
        "A value past p25 or p75 is drawn just outside the band rather than to "
        "scale, so one long reach does not squash every other row. Citations "
        "carry a count and no position: the cohort's papers in this window are "
        "eight to eighteen years old and this record's are at most "
        f"{data.horizon} years old, so setting the two counts side by side would "
        "measure the calendar rather than the work.",
    )
    _close(pdf, fig)


def _trajectory_page(pdf: PdfPages, data: SlideData) -> None:
    """The cohort's record year by year, which a table at the horizon cannot show.

    Every quartile in this report is computed at every career year, and until
    now only the last one reached a page. The shape of the climb is the part a
    reader in year two actually needs: it says what year two looked like, not
    only what year six did.
    """
    by_year: dict[str, dict[int, dict]] = {}
    for row in data.benchmarks:
        year = _float(row.get("career_year"))
        if year is None:
            continue
        by_year.setdefault(row["metric"], {})[int(year)] = row
    if not by_year:
        return

    panels = [m for m in TRAJECTORY_METRICS if len(by_year.get(m, {})) > 1]
    if not panels:
        return

    subject_values = {
        row["metric"]: _float(row.get("value"))
        for row in data.subject
        if row.get("compared") == "yes"
    }
    short = (data.config.subject.name.split() or ["this record"])[0]

    fig = _page()
    _title(fig, "The same cohort, year by year", kicker="2. Across the clock")
    _lede(
        fig,
        "Each panel is one measure counted from the start of the appointment "
        "through that career year. The band is the cohort's middle half and the "
        f"line is its median. {short} is marked at year {data.horizon}, the year "
        "the two sides are compared at.",
    )

    columns = 3
    rows_n = (len(panels) + columns - 1) // columns
    left, right, top, bottom = 0.075, 0.965, 0.755, 0.215
    h_gap, v_gap = 0.095, 0.125
    width = (right - left - h_gap * (columns - 1)) / columns
    height = (top - bottom - v_gap * (rows_n - 1)) / rows_n

    for i, metric in enumerate(panels):
        col, row_i = i % columns, i // columns
        ax = fig.add_axes([
            left + col * (width + h_gap),
            top - height - row_i * (height + v_gap),
            width, height,
        ])
        series = by_year[metric]
        years = sorted(series)
        p25 = [_float(series[y].get("p25")) or 0.0 for y in years]
        p50 = [_float(series[y].get("p50")) or 0.0 for y in years]
        p75 = [_float(series[y].get("p75")) or 0.0 for y in years]

        ax.set_facecolor("white")
        ax.fill_between(years, p25, p75, color=RIBBON, zorder=1, linewidth=0)
        ax.plot(years, p50, color=BAND, lw=2.2, zorder=2)
        ax.plot(years, p50, marker="o", markersize=3, color=BAND,
                linestyle="none", zorder=2)

        highest = max(p75 + [0.0])
        subject_value = subject_values.get(metric)
        if subject_value is not None and data.horizon in series:
            ax.plot([data.horizon], [subject_value], marker="D", markersize=8,
                    color=ACCENT, zorder=4)
            highest = max(highest, subject_value)
        ax.set_ylim(0, highest * 1.24 if highest else 1.0)
        ax.set_xlim(min(years) - 0.35, max(years) + 0.35)
        ax.set_xticks(years)

        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(RULE)
        ax.tick_params(colors=MUTED, labelsize=8, length=2)
        ax.set_xlabel("career year", fontsize=8, color=MUTED, labelpad=2, **FONT)
        if metric in SHARE_METRICS:
            ax.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
        ax.set_title(textwrap.fill(SHORT_LABELS.get(metric, metric), 26),
                     fontsize=10.5, color=INK, pad=8, **FONT)

    handles = [
        plt.Line2D([], [], color=RIBBON, lw=9, label="cohort p25 to p75"),
        plt.Line2D([], [], color=BAND, lw=2.2, label="cohort median"),
    ]
    if subject_values:
        handles.append(
            plt.Line2D([], [], marker="D", linestyle="none", color=ACCENT,
                       label=f"{data.config.subject.name}, at year {data.horizon}")
        )
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.06, 0.135),
               ncol=len(handles), frameon=False, fontsize=9)

    _footnote(
        fig,
        "Counts are cumulative, so a flat stretch is a year that added little "
        "and a step is a year that added a lot. Citations are counted as they "
        "stand today for the papers published by that career year, which is why "
        "the early years look larger here than they did at the time.",
    )
    _close(pdf, fig)


def _norms_page(pdf: PdfPages, data: SlideData) -> None:
    """The subfield's own distribution at the comparison horizon."""
    at_horizon = [
        r for r in data.benchmarks if _float(r.get("career_year")) == data.horizon
    ]
    if not at_horizon:
        return

    fig = _page()
    _title(fig, "The numbers those bands come from",
           kicker=f"3. The cohort at year {data.horizon}")
    _lede(
        fig,
        f"What the cohort of {data.cohort_size:,} people had published by the end "
        f"of career year {data.horizon}, as quartiles across people.",
    )

    rows = []
    for metric in METRIC_ORDER:
        row = next((r for r in at_horizon if r["metric"] == metric), None)
        if row is None:
            continue
        rows.append(
            [METRIC_LABELS.get(metric, metric)]
            + [_cell(row, q) for q in ("p25", "p50", "p75")]
        )
    if not rows:
        plt.close(fig)
        return

    ax = fig.add_axes([0.06, 0.32, 0.88, 0.48])
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=[f"Measured through year {data.horizon}",
                   "Lower quarter (p25)", "Median", "Upper quarter (p75)"],
        cellLoc="center",
        colLoc="center",
        loc="upper center",
        colWidths=[0.34, 0.22, 0.22, 0.22],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1, 2.0)
    for (row_i, col_i), cell in table.get_celld().items():
        cell.set_edgecolor(RULE)
        if row_i == 0:
            cell.set_facecolor("#eef2f6")
            cell.set_text_props(fontweight="bold", color=INK)
        elif row_i % 2 == 0:
            cell.set_facecolor("#fafbfc")
        if col_i == 0:
            cell.set_text_props(ha="left")

    y = _body(
        fig,
        "Read a row like this: a quarter of the cohort was below the first "
        "number, half was below the middle one, and a quarter was above the "
        "last. Parentheses are 95% confidence intervals from a cluster "
        "bootstrap that resamples people rather than papers, because one "
        "person's papers are not independent of each other. A wide interval "
        "means the cohort is small or spread out, and the number should be "
        "leaned on lightly.",
        0.26, size=10, width=120,
    )
    _body(
        fig,
        "A top-quartile venue is top quartile inside this cohort's own venue "
        "list, not against a global journal ranking, because citation rates "
        "differ enormously between subfields. The journals it covers are named "
        "later in this report.",
        y, size=10, width=120,
    )
    _close(pdf, fig)


def _funnel_page(pdf: PdfPages, data: SlideData) -> None:
    """Who got into the cohort, on a scale where every step is visible.

    Drawn on a log axis. The first step keeps tens of thousands of people and
    the last keeps a thousand, so on a linear axis the opening step fills the
    width and every step after it is a stub, which hides exactly what a reader
    needs to judge. Each step also carries the share of the step above that it
    kept, which is what says whether a filter was gentle or drastic.
    """
    if not data.funnel:
        return
    fig = _page()
    _title(fig, "Who ended up in the cohort", kicker="4. How it was built")
    _lede(
        fig,
        "This is the page to read first when a cohort looks wrong. A step that "
        "removes almost everybody, or almost nobody, is usually the one to "
        "question.",
    )

    labels = [row[0] for row in data.funnel]
    kept = [max(row[2], 1) for row in data.funnel]
    shares = [1.0] + [
        kept[i] / kept[i - 1] if kept[i - 1] else 0.0 for i in range(1, len(kept))
    ]

    ax = fig.add_axes([0.235, 0.315, 0.62, 0.46])
    ax.set_facecolor("white")
    positions = range(len(kept))
    ax.barh(positions, kept, color=BAND, height=0.56, zorder=2)
    ax.set_yticks(list(positions))
    ax.set_yticklabels([textwrap.fill(text, 26) for text in labels],
                       fontsize=9.5, color=INK, **FONT)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(1, max(kept) * 4.0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.tick_params(axis="y", colors=MUTED, labelsize=8, length=0)
    ax.tick_params(axis="x", which="both", labelbottom=False, length=0)
    ax.set_xlabel("people remaining, on a log scale so every step stays visible",
                  fontsize=9, color=MUTED, labelpad=8, **FONT)
    ax.grid(axis="x", color=RULE, linewidth=0.8)
    ax.set_axisbelow(True)

    for i, (value, share) in enumerate(zip(kept, shares, strict=True)):
        ax.text(value * 1.14, i - 0.10, f"{value:,}", va="center", fontsize=9.5,
                color=INK, fontweight="bold", **FONT)
        if i:
            ax.text(value * 1.14, i + 0.26, f"kept {share:.0%} of the step above",
                    va="center", fontsize=8, color=MUTED, **FONT)

    rules = "\n".join(
        f"{label}:  {textwrap.shorten(rule, 92, placeholder=' ...')}"
        for label, rule, _kept, _dropped in data.funnel
    )
    fig.text(0.06, 0.255, rules, fontsize=8, color=MUTED, va="top",
             linespacing=1.9, **FONT)
    _footnote(
        fig,
        "The full rule for each step is in results/funnel.csv and in "
        "docs/methods.md. Where a person could not be placed with confidence "
        "they were dropped rather than guessed at, so the cohort is smaller and "
        "cleaner than the subfield it came from, and the people it leaves out "
        "are not a random sample of that subfield.",
    )
    _close(pdf, fig)


def _venues_page(pdf: PdfPages, data: SlideData) -> None:
    """The journals the phrase top quartile covers, and who leads inside them.

    Two panels over one shared list of journals: how much of the cohort's work
    each one carries, and, when the led-versus-co-authored pass has run, how
    much of that work the cohort led. The second panel is what turns a venue
    list into something a reader can act on, because a journal a subfield
    publishes in constantly but rarely leads in is a different kind of venue
    from one it leads in half the time.
    """
    if not data.venues:
        return
    fig = _page()
    _title(fig, "Where this subfield publishes", kicker="5. The venues")
    lead_shares = data.venue_led_share
    _lede(
        fig,
        "The journals the cohort used most, so that a top-quartile venue can be "
        "checked against titles rather than taken on trust."
        + ("  The panel on the right is how much of that work the cohort led."
           if lead_shares else ""),
    )

    top = list(data.venues[:12])
    counts = [count for _n, count, _i, _q in top]
    colours = [BAND if quartile else COHORT for _n, _c, _i, quartile in top]
    names = [
        name if impact is None else f"{name}  ({impact:.1f})"
        for name, _count, impact, _q in top
    ]

    wide = not lead_shares
    ax = fig.add_axes([0.335, 0.265, 0.60 if wide else 0.375, 0.50])
    ax.set_facecolor("white")
    positions = range(len(counts))
    ax.barh(positions, counts, color=colours, height=0.62)
    ax.set_yticks(list(positions))
    ax.set_yticklabels([textwrap.fill(n, 34) for n in names], fontsize=8,
                       color=INK, **FONT)
    ax.invert_yaxis()
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_xlim(0, max(counts) * 1.18)
    ax.set_xlabel(f"cohort papers through year {data.horizon}", fontsize=9,
                  color=MUTED, **FONT)
    for i, value in enumerate(counts):
        ax.text(value + max(counts) * 0.02, i, f"{value:,}", va="center",
                fontsize=8, color=INK, fontweight="bold", **FONT)

    if lead_shares:
        ax2 = fig.add_axes([0.755, 0.265, 0.185, 0.50])
        ax2.set_facecolor("white")
        shares = [lead_shares.get(name, 0.0) for name, _c, _i, _q in top]
        widest = max(shares + [0.01])
        ax2.barh(positions, shares, color=ACCENT, height=0.62, alpha=0.85)
        ax2.set_yticks(list(positions))
        ax2.set_yticklabels([])
        ax2.invert_yaxis()
        for side in ("top", "right", "left"):
            ax2.spines[side].set_visible(False)
        ax2.spines["bottom"].set_color(RULE)
        ax2.tick_params(axis="x", colors=MUTED, labelsize=8)
        ax2.tick_params(axis="y", length=0)
        ax2.set_xlim(0, widest * 1.40)
        ax2.xaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
        ax2.set_xlabel("share the cohort led", fontsize=9, color=MUTED, **FONT)
        for i, value in enumerate(shares):
            ax2.text(value + widest * 0.05, i, f"{value:.0%}", va="center",
                     fontsize=8, color=INK, **FONT)

    fig.legend(
        handles=[
            plt.Line2D([], [], color=BAND, lw=9, label="top quartile in this cohort"),
            plt.Line2D([], [], color=COHORT, lw=9, label="everything else"),
        ],
        loc="lower left", bbox_to_anchor=(0.335, 0.155), ncol=2, frameon=False,
        fontsize=9,
    )
    _footnote(
        fig,
        "The number in brackets after a journal is its 2-year mean citedness "
        "from OpenAlex, a property of the journal and not of any paper in it. "
        "Read this list before trusting the counts elsewhere in the report. "
        "Some conference abstract series carry an ISSN and are typed as "
        "journals by OpenAlex, so they cannot be told apart from a journal in "
        "the data and are counted as articles here. A journal near the top of "
        "this list with an impact near zero is usually one of them.",
    )
    _close(pdf, fig)


def _chaperone_page(pdf: PdfPages, data: SlideData) -> None:
    """Led against co-authored, the question Sekara et al. asked of whole careers.

    This lived only in `chaperone.md` before, which put the finding most likely
    to change how someone reads their own record in a file most people never
    open. It belongs in the document that gets forwarded.

    Two panels, each with its reading directly underneath it rather than in one
    paragraph covering both, because the whole point of the page is that the
    two answer different questions.
    """
    if not data.has_chaperone:
        return
    fig = _page()
    _title(fig, "Who leads the papers that reach the best venues",
           kicker="6. Led against co-authored")
    _lede(
        fig,
        "For the same people over the same window: when a paper reached a "
        "top-quartile venue, was this person leading it? Led means last author, "
        "or flagged as the corresponding one.",
    )

    left_x, right_x = 0.075, 0.575
    ax = fig.add_axes([left_x, 0.455, 0.385, 0.295])
    ax.set_facecolor("white")
    labels = [label for label, _rate in data.role_rates]
    values = [rate or 0.0 for _label, rate in data.role_rates]
    headroom = max(values + [0.01])
    positions = range(len(values))
    colours = [ACCENT if label.startswith("Led") else COHORT for label in labels]
    ax.bar(positions, values, color=colours, width=0.58)
    ax.set_xticks(list(positions))
    ax.set_xticklabels([textwrap.fill(label, 14) for label in labels],
                       fontsize=9, color=INK, **FONT)
    ax.set_ylim(0, headroom * 1.34)
    ax.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_ylabel("papers reaching a top-quartile venue", fontsize=8.5,
                  color=MUTED, **FONT)
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        ax.text(i, value + headroom * 0.04, f"{value:.1%}", ha="center",
                fontsize=10, color=INK, fontweight="bold", **FONT)
        _people, papers = data.role_counts.get(label, (0, 0))
        if papers:
            ax.text(i, value + headroom * 0.145, f"{papers:,} papers",
                    ha="center", fontsize=7.5, color=MUTED, **FONT)
    ax.set_title("Across every paper the cohort wrote", fontsize=11,
                 color=INK, pad=10, **FONT)

    led = data.paired.get("median_led_share")
    middle = data.paired.get("median_middle_share")
    people = int(data.paired.get("people", 0))
    if led is not None and middle is not None:
        ax2 = fig.add_axes([right_x, 0.455, 0.365, 0.295])
        ax2.set_facecolor("white")
        pair_top = max(led, middle)
        ax2.bar([0, 1], [led, middle], color=[ACCENT, COHORT], width=0.48)
        ax2.set_xticks([0, 1])
        ax2.set_xticklabels(["papers they led", "papers they did not lead"],
                            fontsize=9, color=INK, **FONT)
        ax2.set_ylim(0, pair_top * 1.34)
        ax2.yaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
        for side in ("top", "right"):
            ax2.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax2.spines[side].set_color(RULE)
        ax2.tick_params(colors=MUTED, labelsize=8)
        ax2.set_ylabel("median rate within one person", fontsize=8.5,
                       color=MUTED, **FONT)
        for x, value in ((0, led), (1, middle)):
            ax2.text(x, value + pair_top * 0.04, f"{value:.1%}", ha="center",
                     fontsize=10, color=INK, fontweight="bold", **FONT)
        ax2.set_title(f"The same {people:,} people, each their own comparison",
                      fontsize=11, color=INK, pad=10, **FONT)

    _body(
        fig,
        "Every paper counts once, so this reading is dominated by whoever wrote "
        "the most of them.",
        0.400, size=9.5, width=56, color=MUTED, x=left_x,
    )
    if led is not None:
        _body(
            fig,
            "Everyone here is their own control, so field, institution, career "
            "stage and how prolific someone is all cancel out. It drops anyone "
            "without enough papers in both roles.",
            0.400, size=9.5, width=56, color=MUTED, x=right_x,
        )

    y = 0.295
    if data.gap:
        value, low, high = data.gap
        direction = "more often" if value > 0 else "less often"
        interval = (f" (95% confidence interval {low:+.1%} to {high:+.1%})"
                    if low is not None and high is not None else "")
        crosses = low is not None and high is not None and low <= 0 <= high
        _body(
            fig,
            "Pooled across every paper, the cohort's work reached a top-quartile "
            f"venue {abs(value):.1%} {direction} when its members were not "
            f"leading it{interval}. "
            + ("That interval includes zero, so this draw of people does not "
               "settle the direction."
               if crosses else
               "The interval comes from a cluster bootstrap that resamples "
               "people, so it says how far this would move with a different "
               "draw of people from the same subfield.")
            + " Where the two panels disagree, that disagreement is the finding.",
            y, size=10, width=128,
        )

    _footnote(
        fig,
        "After Sekara et al., \"The chaperone effect in scientific publishing\", "
        "PNAS 2018 (doi 10.1073/pnas.1800471115), which followed authors through "
        "time. This is a cross-sectional approximation of that design and not a "
        "replication: the direction of a difference is informative, its size "
        "should not be read against their figures. Where a field does not order "
        "authors by contribution, none of this applies.",
    )
    _close(pdf, fig)


def _caveats_page(pdf: PdfPages, data: SlideData) -> None:
    fig = _page()
    _title(fig, "What this cannot see", kicker="Limits")
    _lede(fig, "Six things to hold in mind before this document is used for "
               "anything.")

    items = [
        ("A publication record is not a person.",
         "Teaching, mentoring, service, funding, software, datasets, patents and "
         "public scholarship do not appear in OpenAlex, and they are a large "
         "part of the job."),
        ("Citations are shown and never placed.",
         "The cohort's papers in this window are years older than this record's, "
         "and citations accumulate with time, so comparing the two counts would "
         "measure the calendar."),
        ("Career start is inferred, not looked up.",
         "It comes from publication patterns rather than from HR records. "
         "Conversions from lecturer to tenure line, clinical appointments, "
         "parental leave and delayed starts are invisible to it, and people who "
         "never changed institution are left out because their trainee years "
         "cannot be told apart from their independent ones."),
        ("The people who are missing are not a random sample.",
         "OpenAlex splits some people across profiles and merges others with "
         "namesakes. The cohort keeps only the people it could identify "
         "confidently, which tilts it toward distinctive names."),
        ("Journal impact says nothing about a paper.",
         "It is a property of the journal. Venue quartiles are computed inside "
         "this cohort's own venue list because citation cultures differ "
         "enormously between subfields."),
        ("This is a description, not an instruction.",
         "These are ranges of what a group of people did. A department that "
         "reads the median as something everyone must reach has misread this "
         "document."),
    ]

    y = 0.805
    for heading, text in items:
        fig.text(0.06, y, heading, fontsize=11.5, color=INK, fontweight="bold",
                 va="top", **FONT)
        y = _body(fig, text, y - 0.032, size=10, width=126) + 0.008

    cohort_note = ""
    if data.cohort_size and data.cohort_size < 40:
        cohort_note = (
            f"This cohort is {data.cohort_size} people, which is small. Read "
            "every quartile in it as indicative only. "
        )
    _footnote(
        fig,
        cohort_note
        + "Cells covering fewer than "
        f"{data.config.cohort.min_cell_size} people are withheld, because a "
        "quartile over a handful of people can identify them. The method in "
        "full is in docs/methods.md. Data: OpenAlex (Priem, Piwowar and Orr, "
        "2022), CC0.",
    )
    _close(pdf, fig)


def build_pdf_report(
    results: str | Path,
    config: Config,
    *,
    path: str | Path | None = None,
    on_progress=None,
) -> Path:
    """Write the whole report as one PDF and return its path.

    Needs nothing on the machine beyond matplotlib, which is the point: the
    Colab path cannot install LibreOffice in a reasonable time.
    """
    results = Path(results)

    # The PDF itself is not text-scanned, and saying why matters. matplotlib
    # writes a string as a run of glyphs broken up by kerning, so "Sparks" is
    # findable in the file and "Taylor" is not: a substring scan would pass a
    # split name and report safety it had not checked. A guardrail that gives
    # false confidence is worse than none.
    #
    # So the guarantee is on the inputs. Every page is drawn from these files
    # and from fixed prose in this module, so a clean input set is a clean PDF.
    # A dirty one refuses to draw at all.
    for name in (FUNNEL_FILENAME, BENCHMARKS_CSV, SUBJECT_CSV, VENUES_CSV,
                 CHAPERONE_CSV):
        source = results / name
        if source.exists():
            assert_aggregates_only(source)

    data = load_slide_data(results, config)
    out = Path(path) if path is not None else results / PDF_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(out) as pdf:
        _cover(pdf, data)
        _subject_page(pdf, data)
        _trajectory_page(pdf, data)
        _norms_page(pdf, data)
        _funnel_page(pdf, data)
        _venues_page(pdf, data)
        _chaperone_page(pdf, data)
        _caveats_page(pdf, data)
        info = pdf.infodict()
        info["Title"] = f"{config.subject.name} against {config.subfield.label}"
        info["Subject"] = (
            "Publication norms through the tenure clock. Aggregates only."
        )
        info["Creator"] = "tenuretrack"

    if on_progress:
        on_progress(f"Wrote {out.name}.")
    return out
