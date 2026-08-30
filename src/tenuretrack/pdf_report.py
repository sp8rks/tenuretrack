"""A standalone PDF of the whole report, built without LibreOffice.

`slides.export_pdf` converts the deck by shelling out to LibreOffice, which is
not on a Colab machine and is a several-minute install. The no-install path is
the one most people use, so the PDF they get at the end cannot depend on it.
This module draws the pages directly with matplotlib, which is already a
dependency because the figures need it.

It reads the pipeline's own output files and recomputes nothing, for the same
reason `slides.py` does: a figure and a table that disagree are worse than
either one alone.

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

from tenuretrack.config import Config  # noqa: E402
from tenuretrack.figures import ACCENT, COHORT, INK, MUTED  # noqa: E402
from tenuretrack.guardrail import assert_aggregates_only  # noqa: E402
from tenuretrack.metrics import BENCHMARKS_CSV  # noqa: E402
from tenuretrack.pool import FUNNEL_FILENAME  # noqa: E402
from tenuretrack.report import SUBJECT_CSV, VENUES_CSV  # noqa: E402
from tenuretrack.slides import SlideData, load_slide_data  # noqa: E402

__all__ = ["PDF_FILENAME", "build_pdf_report"]

PDF_FILENAME = "report.pdf"

PAGE = (11.0, 8.5)
"""US letter, landscape, so the wide comparison panels are not cramped."""

FONT = {"family": "DejaVu Sans"}
BAND = "#3b5b7a"

METRIC_ORDER = (
    "pubs",
    "led",
    "lead_share",
    "citations",
    "h_index",
    "venue_impact",
    "top_quartile_share",
)


def _page():
    fig = plt.figure(figsize=PAGE)
    fig.patch.set_facecolor("white")
    return fig


def _close(pdf: PdfPages, fig) -> None:
    pdf.savefig(fig, facecolor="white")
    plt.close(fig)


def _title(fig, text: str, y: float = 0.93) -> None:
    fig.text(0.06, y, text, fontsize=20, color=INK, fontweight="bold", va="top", **FONT)
    fig.add_artist(plt.Line2D([0.06, 0.16], [y - 0.045, y - 0.045], color=ACCENT, lw=3))


def _body(fig, text: str, y: float, size: float = 10.5, width: int = 108) -> float:
    """Draw a wrapped paragraph and return the y the next one should start at."""
    wrapped = textwrap.fill(text, width)
    lines = wrapped.count(chr(10)) + 1
    fig.text(
        0.06, y, wrapped, fontsize=size, color=INK, va="top", linespacing=1.5, **FONT
    )
    return y - (lines * size * 0.0028) - 0.028


def _tidy(value) -> str:
    """Numbers as a reader writes them: no trailing zeros on a whole count."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number == int(number):
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _cell(row, quartile: str) -> str:
    """One quartile with its confidence interval, as the table shows it."""
    low = _tidy(row[quartile + "_ci_low"])
    high = _tidy(row[quartile + "_ci_high"])
    return f"{_tidy(row[quartile])}   ({low} to {high})"


def _cover(pdf: PdfPages, data: SlideData) -> None:
    fig = _page()
    subject = data.config.subject
    label = data.config.subfield.label or "the subfield"

    fig.text(0.06, 0.80, subject.name, fontsize=30, color=INK, fontweight="bold", **FONT)
    fig.text(
        0.06,
        0.73,
        f"against {label}, at career year {data.horizon}",
        fontsize=17,
        color=MUTED,
        **FONT,
    )
    fig.add_artist(plt.Line2D([0.06, 0.30], [0.69, 0.69], color=ACCENT, lw=4))

    y = 0.62
    y = _body(
        fig,
        f"{subject.name} began a tenure-line appointment at "
        f"{subject.institution_name} in {subject.start_year}, which makes this "
        f"career year {data.career_year}. The comparison is made at year "
        f"{data.horizon}.",
        y,
        size=12,
    )
    y = _body(
        fig,
        f"The cohort is {data.cohort_size} people, each estimated to have begun a "
        f"first independent faculty appointment between "
        f"{data.config.cohort.start_window[0]} and "
        f"{data.config.cohort.start_window[1]} in {label}. {subject.name} is not "
        "among them.",
        y,
        size=12,
    )
    _body(
        fig,
        "These numbers describe what a group of people did. They are not a "
        "standard, nobody in the cohort agreed to be measured, and no part of "
        "this says what any one career should look like.",
        y,
        size=12,
    )
    fig.text(
        0.06,
        0.08,
        "Aggregates only. No cohort member is named in this document."
        + chr(10)
        + "Built with tenuretrack from OpenAlex data (Priem, Piwowar and Orr 2022).",
        fontsize=9,
        color=MUTED,
        va="bottom",
        linespacing=1.6,
        **FONT,
    )
    _close(pdf, fig)


def _ordered(rows):
    return sorted(
        rows,
        key=lambda r: METRIC_ORDER.index(r["metric"])
        if r["metric"] in METRIC_ORDER
        else 99,
    )


def _subject_page(pdf: PdfPages, data: SlideData) -> None:
    """The comparison, one panel per metric, each on its own scale.

    Panels rather than one shared axis: a paper count and a venue impact do not
    belong on the same scale, and normalising them to fit hides the numbers a
    reader came for.
    """
    if not data.subject:
        return
    rows = _ordered(data.subject)
    compared = [r for r in rows if r.get("compared") == "yes"]
    if not compared:
        return

    fig = _page()
    _title(fig, f"{data.config.subject.name} and the cohort")
    short = data.config.subject.name.split()[0]
    n = len(compared)
    slot = 0.90 / n

    for i, row in enumerate(compared):
        ax = fig.add_axes([0.055 + i * slot, 0.30, slot * 0.78, 0.50])
        p25 = float(row["cohort_p25"])
        p50 = float(row["cohort_p50"])
        p75 = float(row["cohort_p75"])
        value = float(row["value"])

        ax.set_facecolor("white")
        # No y axis at all: the three labels on the band say what the ticks
        # would, and a tick column beside every panel crowds six panels into
        # illegibility.
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.axhspan(p25, p75, xmin=0.36, xmax=1.0, color=COHORT, zorder=1)
        ax.plot([0.36, 1.0], [p50, p50], color=BAND, lw=2.2, zorder=2)
        top = max(p75, value) or 1.0
        ax.set_ylim(-top * 0.14, top * 1.34)

        for at, text in (
            (p75, "p75 " + _tidy(p75)),
            (p50, "median " + _tidy(p50)),
            (p25, "p25 " + _tidy(p25)),
        ):
            ax.text(
                0.30, at, text, ha="right", va="center", fontsize=7, color=MUTED, **FONT
            )

        ax.plot([0.72], [value], marker="D", markersize=8, color=ACCENT, zorder=3)
        # Above the marker, not beside it: a long name beside a diamond in the
        # rightmost panel runs off the page, and in the others it lands on the
        # next panel's labels. Below the marker when the subject sits under the
        # median, where "above" would put it on the median's own label.
        above = value >= p50
        ax.text(
            0.72,
            value + (top * 0.08 if above else -top * 0.08),
            short + " " + _tidy(value),
            ha="center",
            va="bottom" if above else "top",
            fontsize=8,
            color=ACCENT,
            fontweight="bold",
            **FONT,
        )
        ax.set_title(
            textwrap.fill(row["label"], 18), fontsize=8.5, color=INK, pad=10, **FONT
        )

    y = 0.20
    for row in (r for r in rows if r.get("compared") != "yes"):
        y = _body(
            fig,
            f"{row['label']}: {_tidy(row['value'])} for {data.config.subject.name}, "
            f"against a cohort p25 to p75 of {_tidy(row['cohort_p25'])} to "
            f"{_tidy(row['cohort_p75'])}. Shown, and deliberately not placed: the "
            "cohort's papers in this window are years older, so putting one count "
            "against the other would measure the calendar rather than the work.",
            y,
            size=9.5,
        )
    _close(pdf, fig)


def _norms_page(pdf: PdfPages, data: SlideData) -> None:
    """The subfield's own distribution at the comparison horizon."""
    at_horizon = [r for r in data.benchmarks if int(r["career_year"]) == data.horizon]
    if not at_horizon:
        return

    fig = _page()
    _title(fig, f"What the subfield published through year {data.horizon}")

    labels = {r["metric"]: r["label"] for r in data.subject} if data.subject else {}
    rows = []
    for metric in METRIC_ORDER:
        row = next((r for r in at_horizon if r["metric"] == metric), None)
        if row is None:
            continue
        rows.append(
            [labels.get(metric, metric)]
            + [_cell(row, q) for q in ("p25", "p50", "p75")]
        )
    if not rows:
        plt.close(fig)
        return

    ax = fig.add_axes([0.06, 0.32, 0.88, 0.48])
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=[f"Metric (through year {data.horizon})", "p25", "Median", "p75"],
        cellLoc="center",
        colLoc="center",
        loc="upper center",
        colWidths=[0.40, 0.20, 0.20, 0.20],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1, 1.9)
    for (row_i, col_i), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e6ea")
        if row_i == 0:
            cell.set_facecolor("#eef2f6")
            cell.set_text_props(fontweight="bold", color=INK)
        elif row_i % 2 == 0:
            cell.set_facecolor("#fafbfc")
        if col_i == 0:
            cell.set_text_props(ha="left")

    _body(
        fig,
        "Parentheses are 95% cluster-bootstrap confidence intervals, resampling "
        "people rather than papers, because one person's papers are not "
        "independent of each other. A top-quartile venue is top quartile inside "
        f"this cohort's own venue list, not globally. The cohort is "
        f"{data.cohort_size} people.",
        0.26,
        size=9.5,
    )
    _close(pdf, fig)


def _funnel_page(pdf: PdfPages, data: SlideData) -> None:
    if not data.funnel:
        return
    fig = _page()
    _title(fig, "How the cohort was built")

    labels = [row[0] for row in data.funnel]
    kept = [row[2] for row in data.funnel]

    ax = fig.add_axes([0.32, 0.30, 0.62, 0.50])
    ax.set_facecolor("white")
    bars = ax.barh(range(len(kept)), kept, color=BAND, height=0.62)
    ax.set_yticks(range(len(kept)))
    ax.set_yticklabels(
        [textwrap.fill(text, 32) for text in labels], fontsize=8.5, color=INK, **FONT
    )
    ax.invert_yaxis()
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.set_xlabel("people", fontsize=9, color=MUTED, **FONT)
    for bar, value in zip(bars, kept, strict=True):
        ax.text(
            bar.get_width() + max(kept) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            va="center",
            fontsize=8.5,
            color=INK,
            fontweight="bold",
            **FONT,
        )

    _body(
        fig,
        "Each filter and how many people it left. This is the page to read first "
        "when a cohort looks wrong: a step that removes almost everybody, or "
        "almost nobody, is usually the one to question. The exact rule for each "
        "step is in results/funnel.csv and in docs/methods.md.",
        0.22,
        size=9.5,
    )
    _close(pdf, fig)


def _venues_page(pdf: PdfPages, data: SlideData) -> None:
    if not data.venues:
        return
    fig = _page()
    _title(fig, "Where the subfield publishes")

    top = list(data.venues[:10])
    names = [
        f"{name}  (impact {impact:.1f})" if impact is not None else name
        for name, _count, impact, _q in top
    ]
    counts = [count for _n, count, _i, _q in top]
    colours = [BAND if quartile else COHORT for _n, _c, _i, quartile in top]

    ax = fig.add_axes([0.38, 0.28, 0.56, 0.54])
    ax.set_facecolor("white")
    bars = ax.barh(range(len(counts)), counts, color=colours, height=0.62)
    ax.set_yticks(range(len(counts)))
    ax.set_yticklabels(
        [textwrap.fill(n, 40) for n in names], fontsize=8, color=INK, **FONT
    )
    ax.invert_yaxis()
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.set_xlabel(
        f"cohort papers through year {data.horizon}", fontsize=9, color=MUTED, **FONT
    )
    for bar, value in zip(bars, counts, strict=True):
        ax.text(
            bar.get_width() + max(counts) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            va="center",
            fontsize=8,
            color=INK,
            fontweight="bold",
            **FONT,
        )

    _body(
        fig,
        "The journals this cohort actually used, so that a top-quartile venue can "
        "be checked against titles rather than taken on trust. Darker shading marks "
        "the venues that are top quartile within this cohort. Impact is 2-year "
        "mean citedness from "
        "OpenAlex, which is a property of a journal and not of any paper in it.",
        0.20,
        size=9.5,
    )
    _close(pdf, fig)


def _caveats_page(pdf: PdfPages, data: SlideData) -> None:
    fig = _page()
    _title(fig, "What this does not tell you")

    y = 0.80
    for text in (
        "Teaching, mentoring, service, funding, software, datasets, and public "
        "scholarship do not appear in OpenAlex, and they are a large part of the "
        "job. A publication record is not a person.",
        "Citations are shown and not compared. The cohort's window papers are "
        "years older than the subject's, and citations accumulate with time, so "
        "placing one count against the other would measure the calendar.",
        "Career start is inferred from publication patterns, not from HR records. "
        "For the subject it is supplied; for the cohort it is estimated, and the "
        "people it could not be estimated for were dropped rather than guessed at.",
        "OpenAlex splits some people across profiles and merges others with "
        "namesakes. The cohort keeps only the people it could identify "
        "confidently, which tilts it slightly toward distinctive names.",
        "Journal impact is a property of a journal, not of a paper in it. Venue "
        "quartiles are computed inside this cohort's own venue list because "
        "citation cultures differ enormously between subfields.",
        "These are descriptive ranges of what a group of people did. A department "
        "that reads the median as something everyone must reach has misread "
        "this document.",
    ):
        y = _body(fig, text, y, size=11)

    fig.text(
        0.06,
        0.08,
        "The method in full is in docs/methods.md. The chaperone analysis is a "
        "cross-sectional approximation of Sekara et al., PNAS 2018 "
        "(doi 10.1073/pnas.1800471115).",
        fontsize=9,
        color=MUTED,
        va="bottom",
        **FONT,
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
    # So the guarantee is on the inputs. Every page is drawn from these four
    # files and from fixed prose in this module, so a clean input set is a
    # clean PDF. A dirty one refuses to draw at all.
    for name in (FUNNEL_FILENAME, BENCHMARKS_CSV, SUBJECT_CSV, VENUES_CSV):
        source = results / name
        if source.exists():
            assert_aggregates_only(source)

    data = load_slide_data(results, config)
    out = Path(path) if path is not None else results / PDF_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(out) as pdf:
        _cover(pdf, data)
        _subject_page(pdf, data)
        _norms_page(pdf, data)
        _funnel_page(pdf, data)
        _venues_page(pdf, data)
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
