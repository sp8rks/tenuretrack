"""Place the subject against the cohort and write the report (task 6).

This is the file the subject actually reads, so the wording carries as much
weight as the arithmetic. Three rules govern it.

**Compare only at matching career years.** A person in year 4 is placed against
the cohort at year 4, never against the year-6 table. Where the subject is past
the horizon, the comparison happens at the horizon.

**Citations are reported and never compared.** The cohort's window papers are
eight to eighteen years old and the subject's are nought to six. Citation counts
between them measure elapsed time, not scholarship. The number is shown because
the subject wants it, and it carries a sentence saying why it has no quartile
beside it.

**Positions are locations, not judgements.** "Between p25 and the median" is a
statement about a distribution. "On track" is a statement about a person's
career, which this tool has no standing to make and no data to support.

Everything written here goes to `results/`, so the only person who may be named
is the subject, and only because they ran the tool on themselves.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tenuretrack.config import Config
from tenuretrack.guardrail import assert_aggregates_only
from tenuretrack.metrics import (
    METRICS,
    MemberMetrics,
    Quartiles,
    member_metrics,
)
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.pool import Funnel
from tenuretrack.works import Work, fetch_works, has_byline_at

__all__ = [
    "BELOW_P25",
    "REPORT_MD",
    "TOP_VENUES",
    "SubjectPlacement",
    "build_report",
    "comparison_horizon",
    "position_of",
    "subject_works",
    "top_venues",
    "write_report",
    "write_subject_csv",
    "write_venues_csv",
    "load_venues",
]

REPORT_MD = "report.md"
SUBJECT_CSV = "subject.csv"
VENUES_CSV = "venues.csv"
TOP_VENUES = 15

BELOW_P25 = "below p25"
P25_TO_MEDIAN = "between p25 and the median"
AT_MEDIAN = "at the median"
MEDIAN_TO_P75 = "between the median and p75"
ABOVE_P75 = "above p75"

NOT_COMPARED = {"citations"}
"""Metrics reported for the subject but never given a position.

Citations accumulate with elapsed time. The cohort's window papers have had
eight to eighteen years to collect them and the subject's have had at most six,
so any comparison would measure the calendar.
"""


@dataclass(frozen=True)
class SubjectPlacement:
    """Where the subject sits on one metric, or why they were not placed."""

    metric: str
    label: str
    value: float | None
    position: str | None
    quartiles: Quartiles | None
    compared: bool


def comparison_horizon(career_year: int, horizon_years: int) -> int:
    """The career year at which subject and cohort are compared.

    Their own year while they are inside the clock, the horizon once they are
    past it. Comparing a year-11 record against a year-6 cohort would credit
    the subject for five extra years of work.
    """
    return max(1, min(career_year, horizon_years))


def position_of(value: float | None, quartiles: Quartiles | None) -> str | None:
    """Where one number falls in a distribution, said as a location."""
    if value is None or quartiles is None or quartiles.suppressed:
        return None
    if quartiles.p25 is None or quartiles.p50 is None or quartiles.p75 is None:
        return None
    if value < quartiles.p25:
        return BELOW_P25
    if value == quartiles.p50:
        return AT_MEDIAN
    if value < quartiles.p50:
        return P25_TO_MEDIAN
    if value <= quartiles.p75:
        return MEDIAN_TO_P75
    return ABOVE_P75


def place_subject(
    metrics: MemberMetrics, rows: Sequence[Quartiles], horizon: int
) -> list[SubjectPlacement]:
    """The subject's whole row, metric by metric."""
    by_key = {r.metric: r for r in rows if r.horizon == horizon}
    placements: list[SubjectPlacement] = []
    for metric in METRICS:
        quartiles = by_key.get(metric.key)
        value = metrics.value(metric.key)
        compared = metric.key not in NOT_COMPARED
        placements.append(
            SubjectPlacement(
                metric=metric.key,
                label=metric.label,
                value=value,
                position=position_of(value, quartiles) if compared else None,
                quartiles=quartiles,
                compared=compared,
            )
        )
    return placements


def subject_works(
    client: OpenAlexClient, config: Config, this_year: int
) -> list[Work]:
    """The subject's papers under their own institution's byline.

    Anchored, unlike a cohort member's. For the subject the question is what
    they did in this job, and their trainee papers carry a different byline.
    """
    subject = config.subject
    works = fetch_works(
        client, list(subject.openalex_author_ids), subject.start_year, this_year
    )
    return [
        w
        for w in works
        if has_byline_at(w, subject.openalex_author_ids, subject.institution_ror)
    ]


def top_venues(
    papers: Sequence[Work],
    impacts: Mapping[str, float],
    cutoff: float | None,
    *,
    limit: int = TOP_VENUES,
) -> list[tuple[str, int, float | None, bool]]:
    """The journals this subfield actually publishes in, by paper count.

    Counted over the cohort's window journal articles, the same set the
    top-quartile cutoff comes from. Counting every record on a person's profile
    instead put arXiv, SSRN and two conference-abstract series at the top of
    this table, which describes where the subfield deposits and meets rather
    than where it publishes.

    Aggregate over the whole cohort, so it names venues and never people. This
    is what makes "top-quartile venue" checkable: a reader can see which titles
    the phrase covers in their own field.
    """
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for work in papers:
        if work.source_id:
            counts[work.source_id] += 1
            names.setdefault(work.source_id, work.source_name or work.source_id)

    out = []
    for source_id, count in counts.most_common(limit):
        impact = impacts.get(source_id)
        is_top = bool(cutoff is not None and impact is not None and impact >= cutoff)
        out.append((names.get(source_id, source_id), count, impact, is_top))
    return out


def write_subject_csv(
    path: str | Path,
    placements: Sequence[SubjectPlacement],
    *,
    horizon: int,
    career_year: int,
) -> Path:
    """The subject's row, machine-readable, so the deck never retypes a number.

    The slides read this rather than parsing the prose report, which is how the
    deck and the report are kept from disagreeing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "career_year",
                "compared_at",
                "metric",
                "label",
                "value",
                "cohort_p25",
                "cohort_p50",
                "cohort_p75",
                "position",
                "compared",
            ]
        )
        for placement in placements:
            metric = _metric(placement.metric)
            quartiles = placement.quartiles
            withheld = quartiles is None or quartiles.suppressed
            writer.writerow(
                [
                    career_year,
                    horizon,
                    placement.metric,
                    metric.label,
                    _fmt(placement.value, metric.decimals),
                    "" if withheld else _fmt(quartiles.p25, metric.decimals),
                    "" if withheld else _fmt(quartiles.p50, metric.decimals),
                    "" if withheld else _fmt(quartiles.p75, metric.decimals),
                    placement.position or ("not compared" if not placement.compared else ""),
                    "yes" if placement.compared else "no",
                ]
            )
    assert_aggregates_only(path)
    return path


def write_venues_csv(
    path: str | Path, venues: Sequence[tuple[str, int, float | None, bool]]
) -> Path:
    """The subfield's venues, machine-readable, so the deck reads rather than reparses."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["venue", "cohort_papers", "impact", "top_quartile"])
        for name, count, impact, is_top in venues:
            writer.writerow(
                [name, count, "" if impact is None else f"{impact:.4f}",
                 "yes" if is_top else "no"]
            )
    assert_aggregates_only(path)
    return path


def load_venues(results: str | Path) -> list[tuple[str, int, float | None, bool]]:
    """Read the venue table back, for the deck."""
    path = Path(results) / VENUES_CSV
    if not path.exists():
        return []
    out = []
    for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines()):
        impact = row.get("impact") or ""
        out.append(
            (
                row["venue"],
                int(row["cohort_papers"]),
                float(impact) if impact else None,
                row["top_quartile"] == "yes",
            )
        )
    return out


# --------------------------------------------------------------------- writing


def _fmt(value: float | None, decimals: int) -> str:
    return "" if value is None else f"{value:.{decimals}f}"


def _metric(key: str):
    for metric in METRICS:
        if metric.key == key:
            return metric
    raise KeyError(key)


def write_report(
    path: str | Path,
    *,
    config: Config,
    horizon: int,
    career_year: int,
    final_year_incomplete: bool,
    extension: int = 0,
    placements: Sequence[SubjectPlacement],
    rows: Sequence[Quartiles],
    venues: Sequence[tuple[str, int, float | None, bool]],
    funnel: Funnel,
    cohort_size: int,
    institutions: int,
) -> Path:
    """Write `results/report.md` and prove it carries nothing identifying."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subject = config.subject
    label = config.subfield.label

    lines = [
        f"# {subject.name} against {label}, at career year {horizon}",
        "",
        f"{subject.name} began a tenure-line appointment at "
        f"{subject.institution_name} in {subject.start_year}, which makes this "
        f"calendar year {career_year} of the appointment.",
    ]
    if extension:
        window_end = subject.start_year + horizon + extension - 1
        lines.append(
            f"The clock was stopped for {extension} year(s), so this is year "
            f"{horizon} of the tenure clock and the comparison happens there. "
            f"Papers are counted across {subject.start_year} to {window_end}, "
            "all the calendar years available, because stopping a clock grants "
            "time rather than removing the work done in it. Cohort members at "
            f"year {horizon} had {horizon} calendar years."
        )
    if final_year_incomplete:
        lines.append(
            f"Career year {horizon} is {subject.start_year + horizon - 1}, which "
            "is still running. Everything counted for this record stops at "
            "today, while every cohort member had the whole of their year "
            f"{horizon}. Read this record's figures as a partial year short."
        )
    if career_year > horizon:
        lines.append(
            f"The cohort is compared at year {horizon}, the end of the benchmark "
            "window, because comparing a longer record against a shorter one "
            "would credit the extra years to one side."
        )
    lines += [
        "",
        f"The cohort is {cohort_size} people at {institutions} institutions, each "
        "estimated to have begun a first independent faculty appointment between "
        f"{config.cohort.start_window[0]} and {config.cohort.start_window[1]} in "
        f"{label}. {subject.name} is not among them.",
    ]
    lag = subject.start_year - config.cohort.start_window[1]
    if lag > 0:
        lines += [
            "",
            f"Every one of them began at least {lag} year(s) before "
            f"{subject.name} did, because nobody who started more recently has "
            f"finished {horizon} career years yet. Publishing conventions move, "
            "so read the gap in years as part of the comparison.",
        ]
    lines += [
        "",
        "These numbers describe what a group of people did. They are not a "
        "standard, nobody in the cohort agreed to be measured, and no part of "
        "this says what any one career should look like.",
        "",
        f"## {subject.name} and the cohort at year {horizon}",
        "",
        "| | This record | Cohort p25 | Cohort median | Cohort p75 | Position |",
        "|---|---|---|---|---|---|",
    ]

    for placement in placements:
        metric = _metric(placement.metric)
        quartiles = placement.quartiles
        value = _fmt(placement.value, metric.decimals)
        if quartiles is None or quartiles.suppressed:
            lines.append(f"| {metric.label} | {value} | withheld | withheld | withheld | |")
            continue
        position = "not compared" if not placement.compared else (placement.position or "")
        lines.append(
            f"| {metric.label} | {value} | "
            f"{_fmt(quartiles.p25, metric.decimals)} | "
            f"{_fmt(quartiles.p50, metric.decimals)} | "
            f"{_fmt(quartiles.p75, metric.decimals)} | {position} |"
        )

    lines += [
        "",
        "### Why citations have no position",
        "",
        "The cohort's papers in this window are eight to eighteen years old. "
        f"{subject.name}'s are at most {horizon}. Citations accumulate with time, "
        "so placing one count against the other would measure the calendar rather "
        "than the work. The count is shown because it is worth knowing, and left "
        "unplaced because the comparison would not mean anything.",
        "",
        "## What the subfield publishes in",
        "",
        "The journals the cohort used most, so that \"top-quartile venue\" can be "
        "checked against titles rather than taken on trust. Impact is "
        "`2yr_mean_citedness` from OpenAlex, and the quartile is computed inside "
        "this cohort.",
        "",
        "| Venue | Cohort papers | Impact | Top quartile |",
        "|---|---|---|---|",
    ]
    venue_note = (
        "Read this list before trusting the counts above. Some conference "
        "abstract series carry an ISSN and are typed as journals by OpenAlex, "
        "so they are indistinguishable from a journal in the data and are "
        "counted as articles here. A venue near the top of this table with an "
        "impact near zero is usually one of them, and every count in this "
        "report includes it."
    )
    for name, count, impact, is_top in venues:
        lines.append(
            f"| {name} | {count} | {_fmt(impact, 2) or 'not published'} | "
            f"{'yes' if is_top else ''} |"
        )

    lines += [
        "",
        venue_note,
        "",
        "## How the cohort was built",
        "",
        "| Step | Rule | People left | Removed |",
        "|---|---|---|---|",
    ]
    for step in funnel.steps:
        lines.append(f"| {step.label} | {step.rule} | {step.kept} | {step.dropped} |")

    lines += [
        "",
        "Read this table before the numbers above. If a step removed far more "
        "people than seems right, or the topics are not the ones this record "
        "belongs to, the cohort is answering a different question and the "
        "comparison does not hold.",
        "",
        "## What is not here",
        "",
        "Teaching, mentoring, service, funding, software, datasets, patents and "
        "public scholarship are absent from OpenAlex and are a large part of the "
        "job. See `docs/beyond-papers.md`.",
        "",
        "Career start is estimated from publication bylines for everyone in the "
        "cohort. Lecturer-to-tenure-line conversions, clinical appointments, "
        "parental leave and delayed starts are invisible to it, and people who "
        "never changed institution are excluded because their trainee years "
        "cannot be told apart from their independent ones.",
        "",
        "OpenAlex splits some people across profiles and merges others with "
        "namesakes. The cohort keeps only people it could identify confidently, "
        "which tilts it toward distinctive names.",
        "",
        f"Cells covering fewer than {config.cohort.min_cell_size} people are "
        "withheld, because a quartile over a handful of people can identify them.",
        "",
        "Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, 2022), "
        "CC0.",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    assert_aggregates_only(path)
    return path


# ------------------------------------------------------------- orchestration


def build_report(
    client: OpenAlexClient,
    config: Config,
    benchmarks,
    funnel: Funnel,
    *,
    this_year: int,
    results_dir: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[Path, MemberMetrics, int]:
    """Measure the subject, place them, and write the report."""
    results = Path(results_dir) if results_dir is not None else config.output.dir
    subject_spec = config.subject
    career_year = subject_spec.career_year(this_year)
    extension = subject_spec.clock_extension_years
    clock_year = max(1, career_year - extension)
    horizon = comparison_horizon(clock_year, config.cohort.horizon_years)

    # A stopped clock grants calendar time, it does not remove the work done in
    # that time. So the subject is compared at their clock year while their
    # papers are counted across the calendar years they actually had.
    subject_window = horizon + extension
    final_year_incomplete = subject_spec.start_year + subject_window - 1 >= this_year

    works = subject_works(client, config, this_year)
    if on_progress:
        on_progress(
            f"Subject: {len(works)} journal-eligible papers under the "
            f"{config.subject.institution_name} byline."
        )

    metrics = member_metrics(
        works,
        list(config.subject.openalex_author_ids),
        config.subject.start_year,
        subject_window,
        config.cohort.article_types,
        benchmarks.impacts,
        benchmarks.cutoff,
        config.cohort.excluded_venues,
    )
    placements = place_subject(metrics, benchmarks.rows, horizon)
    venues = top_venues(
        benchmarks.headline_papers, benchmarks.impacts, benchmarks.cutoff
    )
    cohort_size = len(benchmarks.per_member.get(horizon, ()))

    write_venues_csv(results / VENUES_CSV, venues)
    write_subject_csv(
        results / SUBJECT_CSV,
        placements,
        horizon=horizon,
        career_year=career_year,
    )
    path = write_report(
        results / REPORT_MD,
        config=config,
        horizon=horizon,
        career_year=career_year,
        extension=extension,
        final_year_incomplete=final_year_incomplete,
        placements=placements,
        rows=benchmarks.rows,
        venues=venues,
        funnel=funnel,
        cohort_size=cohort_size,
        institutions=benchmarks.institutions,
    )
    if on_progress:
        on_progress(f"Wrote {path}.")
    return path, metrics, horizon
