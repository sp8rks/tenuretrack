"""The six-slide deck (task 8).

Every number on a slide is read from the files in `results/` that the pipeline
wrote. Nothing is recomputed and nothing is retyped, so the deck and the report
cannot disagree: if a slide is wrong, the report is wrong the same way, and one
fix corrects both.

The finished `.pptx` goes through the aggregates-only guardrail before it is
kept. A deck is the artifact most likely to be forwarded to a committee, so it
is the one that most needs to be checked, and it is checked as a file rather
than as an intention.

Format follows `.claude/skills/deck-builder`.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from tenuretrack.figures import ACCENT, dot_and_range_chart, funnel_chart, venue_chart
from tenuretrack.guardrail import GuardrailViolation, assert_aggregates_only
from tenuretrack.slide_data import (
    SlideData,
    _float,
    load_slide_data,
    subject_slug,
)

__all__ = [
    "SlideData",
    "build_slides",
    "export_pdf",
    "load_slide_data",
    "subject_slug",
]

FIGURES_DIR = "figures"
TITLE_SIZE = Pt(30)
HEAD_SIZE = Pt(22)
BODY_SIZE = Pt(13)
SMALL_SIZE = Pt(10)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x6A, 0x6A, 0x6A)
ACCENT_RGB = RGBColor.from_string(ACCENT.lstrip("#").upper())

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.6)


# ------------------------------------------------------------------ drawing


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _text(
    slide,
    text: str,
    *,
    left,
    top,
    width,
    height,
    size=BODY_SIZE,
    bold=False,
    color=INK,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    lines = text.split("\n")
    for i, line in enumerate(lines):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        run = para.add_run()
        run.text = line
        run.font.size = size
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = "DejaVu Sans"
    return box


def _heading(slide, text: str):
    _text(
        slide, text, left=MARGIN, top=Inches(0.4), width=SLIDE_W - 2 * MARGIN,
        height=Inches(0.8), size=HEAD_SIZE, bold=True,
    )


def _table(slide, rows: Sequence[Sequence[str]], *, left, top, width, height):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), left, top, width, height)
    table = shape.table
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(value)
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = SMALL_SIZE
                    run.font.bold = r == 0
                    run.font.color.rgb = INK
                    run.font.name = "DejaVu Sans"
    return table


def _notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


# ------------------------------------------------------------------- slides


def build_slides(
    data: SlideData,
    results: str | Path,
    *,
    today: _dt.date | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Write the deck, then prove it carries nothing identifying."""
    results = Path(results)
    figures = results / FIGURES_DIR
    today = today or _dt.date.today()
    subject = data.config.subject
    label = data.config.subfield.label

    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    body_w = SLIDE_W - 2 * MARGIN

    # 1. Title
    slide = _blank(prs)
    _text(
        slide, f"{subject.name}", left=MARGIN, top=Inches(2.1), width=body_w,
        height=Inches(1.0), size=TITLE_SIZE, bold=True,
    )
    _text(
        slide,
        f"{subject.institution_name}\n"
        f"{label}, career year {data.career_year}\n"
        f"Compared against {data.cohort_size} people at career year {data.horizon}",
        left=MARGIN, top=Inches(3.1), width=body_w, height=Inches(1.6), size=BODY_SIZE,
    )
    _text(
        slide,
        f"Generated {today.isoformat()} from OpenAlex (Priem, Piwowar and Orr, "
        "2022), CC0. These numbers describe what a group of people did. They are "
        "not a standard.",
        left=MARGIN, top=Inches(6.2), width=body_w, height=Inches(0.9),
        size=SMALL_SIZE, color=MUTED,
    )

    # 2. How the cohort was built
    slide = _blank(prs)
    _heading(slide, "How the cohort was built")
    if data.funnel:
        chart = funnel_chart(
            [(label_, kept) for label_, _rule, kept, _dropped in data.funnel],
            figures / "funnel.png",
        )
        slide.shapes.add_picture(str(chart), MARGIN, Inches(1.3), width=Inches(7.4))
    topics = "\n".join(
        f"{t.id}  {t.name}" for t in data.config.subfield.topics
    )
    _text(
        slide, f"Topics defining the subfield\n{topics}",
        left=Inches(8.2), top=Inches(1.4), width=Inches(4.6), height=Inches(3.0),
        size=SMALL_SIZE,
    )
    _text(
        slide,
        "The cohort is people whose work sits in these topics and whose first "
        "independent faculty appointment could be dated confidently from their "
        "bylines. It is not everyone in the subfield, and the people it drops "
        "are not a random sample of it.",
        left=MARGIN, top=Inches(6.0), width=body_w, height=Inches(1.0), size=SMALL_SIZE,
        color=MUTED,
    )

    # 3. Subfield norms
    slide = _blank(prs)
    _heading(slide, f"What the subfield published through year {data.horizon}")
    rows = [["Metric", "p25", "Median", "p75"]]
    for row in data.benchmarks:
        if int(row["career_year"]) != data.horizon:
            continue
        rows.append(
            [
                row["metric"].replace("_", " "),
                row["p25"] or "withheld",
                row["p50"] or "withheld",
                row["p75"] or "withheld",
            ]
        )
    if len(rows) > 1:
        _table(
            slide, rows, left=MARGIN, top=Inches(1.3),
            width=Inches(8.0), height=Inches(0.4) * len(rows),
        )
    _text(
        slide,
        "Quartiles across people, not averages. Citations are counted as they "
        "stand today, for papers that are eight to eighteen years old.",
        left=MARGIN, top=Inches(6.3), width=body_w, height=Inches(0.8),
        size=SMALL_SIZE, color=MUTED,
    )
    _notes(
        slide,
        "Every figure is a quartile across cohort members. The middle half of "
        "the cohort sat between p25 and p75.",
    )

    # 4. Subject against the cohort
    slide = _blank(prs)
    _heading(slide, f"{subject.name} and the cohort at year {data.horizon}")
    chart_rows = []
    for row in data.subject:
        chart_rows.append(
            (
                row["label"],
                _float(row["value"]),
                _float(row["cohort_p25"]),
                _float(row["cohort_p50"]),
                _float(row["cohort_p75"]),
                row["compared"] == "yes",
            )
        )
    if chart_rows:
        chart = dot_and_range_chart(
            chart_rows, figures / "subject.png", subject_name=subject.name
        )
        slide.shapes.add_picture(str(chart), MARGIN, Inches(1.2), width=Inches(8.6))
    positions = "\n".join(
        f"{row['label']}: {row['position']}" for row in data.subject if row["position"]
    )
    _text(
        slide, positions, left=Inches(9.1), top=Inches(1.5), width=Inches(3.7),
        height=Inches(4.0), size=SMALL_SIZE,
    )
    _text(
        slide,
        "Citations are shown and not placed: the cohort's papers have had far "
        "longer to collect them.",
        left=MARGIN, top=Inches(6.5), width=body_w, height=Inches(0.6),
        size=SMALL_SIZE, color=MUTED,
    )
    _notes(
        slide,
        "Subject and cohort are compared at the same career year. Positions are "
        "locations in a distribution, not judgements about a career.",
    )

    # 5. Venues
    slide = _blank(prs)
    _heading(slide, "Where this subfield publishes")
    if data.venues:
        chart = venue_chart(data.venues[:12], figures / "venues.png")
        slide.shapes.add_picture(str(chart), MARGIN, Inches(1.3), width=Inches(7.2))
    if data.role_rates:
        from tenuretrack.figures import role_rate_chart

        chart = role_rate_chart(data.role_rates, figures / "roles.png")
        slide.shapes.add_picture(str(chart), Inches(8.2), Inches(1.6), width=Inches(4.4))
        _text(
            slide, "Top-quartile venue rate by authorship role",
            left=Inches(8.2), top=Inches(1.2), width=Inches(4.4), height=Inches(0.4),
            size=SMALL_SIZE, color=MUTED,
        )
    _text(
        slide,
        "Top quartile means top quartile of venue impact within this cohort, not "
        "a global journal list. A venue near the top with an impact near zero is "
        "usually a conference abstract series that OpenAlex types as a journal.",
        left=MARGIN, top=Inches(6.4), width=body_w, height=Inches(0.8),
        size=SMALL_SIZE, color=MUTED,
    )

    # 6. Caveats
    slide = _blank(prs)
    _heading(slide, "What these numbers cannot see")
    caveats = [
        "Teaching, mentoring, service, funding, software, datasets and public "
        "scholarship are absent from OpenAlex and are a large part of the job.",
        "Career start is estimated from bylines for everyone in the cohort. "
        "Lecturer-to-tenure-line conversions, clinical appointments, parental "
        "leave and delayed starts are invisible to it.",
        "People who never changed institution are excluded, because their "
        "trainee years cannot be told apart from their independent ones.",
        "Corresponding-author flags are missing for many journals and years, so "
        "last position carries most of the weight in deciding who led a paper.",
        "Venue impact is journal-level. It says nothing about an individual "
        "paper.",
        "OpenAlex splits some people across profiles and merges others with "
        "namesakes, which tilts the cohort toward distinctive names.",
    ]
    if data.cohort_size < 40:
        caveats.insert(
            0,
            f"This cohort is {data.cohort_size} people. Read every quartile as "
            "indicative only.",
        )
    _text(
        slide, "\n\n".join(f"- {c}" for c in caveats),
        left=MARGIN, top=Inches(1.4), width=body_w, height=Inches(5.0), size=BODY_SIZE,
    )

    slug = subject_slug(subject.name)
    path = results / f"{slug}.pptx"
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)

    try:
        assert_aggregates_only(path)
    except GuardrailViolation:
        path.unlink(missing_ok=True)
        raise

    if on_progress:
        on_progress(f"Wrote {path.name} (6 slides).")
    return path


def export_pdf(
    pptx_path: str | Path, *, on_progress: Callable[[str], None] | None = None
) -> Path | None:
    """Convert to PDF with LibreOffice when it is there, and say so when it is not.

    Never installs anything. A missing converter is a normal state on a fresh
    machine and on Colab, not a failure of the run.
    """
    pptx_path = Path(pptx_path)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        if on_progress:
            on_progress(
                "PDF export skipped: LibreOffice was not found. Install it and "
                "rerun `tenuretrack slides`, or open the .pptx and export from "
                "there."
            )
        return None

    try:
        subprocess.run(  # noqa: S603
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pptx_path.parent),
                str(pptx_path),
            ],
            check=True,
            capture_output=True,
            timeout=300,
            env={**os.environ, "HOME": str(pptx_path.parent)},
        )
    except (subprocess.SubprocessError, OSError) as exc:
        if on_progress:
            on_progress(f"PDF export failed, leaving the .pptx in place: {exc}")
        return None

    pdf = pptx_path.with_suffix(".pdf")
    if not pdf.exists():
        if on_progress:
            on_progress("PDF export produced no file, leaving the .pptx in place.")
        return None
    if on_progress:
        on_progress(f"Wrote {pdf.name}.")
    return pdf
