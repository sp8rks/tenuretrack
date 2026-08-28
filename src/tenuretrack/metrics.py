"""Per-person metrics through each year of the clock, and cohort quartiles.

This is TASKS.md task 5. It answers the question the whole tool exists for: at
career year N, what did the people in this subfield have published?

Two rules shape everything here.

**People are the unit, not papers.** Every quartile is taken across cohort
members, and the bootstrap resamples members rather than papers. A cohort where
one prolific person wrote a fifth of the papers would otherwise report that
person's habits as the subfield's norm.

**Quartiles, never an average.** A mean publication count is pulled around by
the top of the distribution and describes nobody. p25, p50 and p75 say where
the middle half of a real group actually sat, and the bootstrap says how much
of that spread is the cohort being finite.

Everything written here goes to `results/`, so nothing in this module may emit
a name, an OpenAlex ID, or a per-person row. The writers call the guardrail
before returning, and cells thinner than `min_cell_size` people are suppressed
rather than published.
"""

from __future__ import annotations

import csv
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tenuretrack.career import (
    TRAINEE_LOOKBACK_YEARS,
    WORKS_FILENAME,
    StartEstimate,
    load_works,
)
from tenuretrack.config import Config
from tenuretrack.guardrail import assert_aggregates_only
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.works import (
    LED,
    Work,
    fetch_works_by_author,
    is_journal_article,
    role_of,
)

__all__ = [
    "METRICS",
    "MemberMetrics",
    "Quartiles",
    "BenchmarkResult",
    "benchmark_table",
    "build_benchmarks",
    "build_metrics",
    "collect_member_works",
    "bootstrap_quartiles",
    "fetch_venue_impacts",
    "h_index",
    "member_metrics",
    "top_quartile_cutoff",
    "window_papers",
    "write_benchmarks_csv",
    "write_benchmarks_md",
]

SOURCES_SELECT = "id,display_name,type,summary_stats,is_in_doaj"
SOURCE_BATCH = 50
"""Source IDs per lookup. OpenAlex takes up to 50 values in one OR filter."""

BENCHMARKS_CSV = "benchmarks.csv"
BENCHMARKS_MD = "benchmarks.md"

CI_LOW, CI_HIGH = 2.5, 97.5
"""Percentiles of the bootstrap distribution that make a 95% interval."""


@dataclass(frozen=True, slots=True)
class Metric:
    """One thing measured about a person, and how to say it in a table."""

    key: str
    label: str
    decimals: int = 0
    is_share: bool = False


METRICS: tuple[Metric, ...] = (
    Metric("pubs", "Journal articles", 0),
    Metric("led", "Led articles (last or corresponding)", 0),
    Metric("lead_share", "Share of articles led", 2, is_share=True),
    Metric("citations", "Citations to those articles", 0),
    Metric("h_index", "h-index over those articles", 0),
    Metric("venue_impact_median", "Median venue impact", 2),
    Metric("top_quartile_share", "Share in top-quartile venues", 2, is_share=True),
)


@dataclass(frozen=True)
class BenchmarkResult:
    """Everything task 5 produced, including what task 6 needs to reuse."""

    per_member: dict
    rows: list
    impacts: dict
    cutoff: float | None
    works_by_member: dict
    headline_papers: list
    """The cohort's window journal articles. What the venue list must count:
    everything else on a person's record includes preprints and meeting
    abstracts, which are not where the subfield publishes."""
    institutions: int
    csv_path: Path
    md_path: Path


@dataclass(frozen=True, slots=True)
class MemberMetrics:
    """One person's record through career year N. Never leaves `data/`."""

    author_id: str
    horizon: int
    pubs: int = 0
    led: int = 0
    lead_share: float | None = None
    citations: int = 0
    h_index: int = 0
    venue_impact_median: float | None = None
    top_quartile_share: float | None = None

    def value(self, key: str) -> float | None:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class Quartiles:
    """Where the middle half of the cohort sat, and how sure of that we are."""

    metric: str
    horizon: int
    n: int
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p25_lo: float | None = None
    p25_hi: float | None = None
    p50_lo: float | None = None
    p50_hi: float | None = None
    p75_lo: float | None = None
    p75_hi: float | None = None
    suppressed: bool = False
    """True when fewer than `min_cell_size` people had a value, so the numbers
    are withheld: a quartile over three people can identify them."""


# ------------------------------------------------------------- pure: one person


def h_index(citations: Iterable[int]) -> int:
    """The largest h where h papers have at least h citations each."""
    counts = sorted((int(c) for c in citations), reverse=True)
    h = 0
    for i, count in enumerate(counts, start=1):
        if count >= i:
            h = i
        else:
            break
    return h


def window_papers(
    works: Sequence[Work],
    start_year: int,
    horizon: int,
    article_types: Sequence[str],
) -> list[Work]:
    """Journal articles in career years 1 through `horizon`.

    Career year 1 is the calendar year the appointment began, so the window is
    `start_year` through `start_year + horizon - 1` inclusive.
    """
    last = start_year + horizon - 1
    return [
        w
        for w in works
        if start_year <= w.year <= last and is_journal_article(w, article_types)
    ]


def member_metrics(
    works: Sequence[Work],
    author_ids: Sequence[str],
    start_year: int,
    horizon: int,
    article_types: Sequence[str],
    impacts: Mapping[str, float],
    cutoff: float | None,
) -> MemberMetrics:
    """Everything measured about one person through career year `horizon`.

    Cohort members count every byline: the start estimate already anchored them
    to an institution, so a second institutional filter would drop the papers
    they wrote after moving. The subject is anchored, because for them the
    question is what they did in this job.

    A share over zero papers is `None`, not zero. Someone with nothing published
    yet has no lead share, and averaging a zero in would drag the cohort down
    with a number that means "not applicable".
    """
    papers = window_papers(works, start_year, horizon, article_types)
    author_id = author_ids[0] if author_ids else ""
    if not papers:
        return MemberMetrics(author_id=author_id, horizon=horizon)

    led = sum(1 for p in papers if role_of(p, author_ids) == LED)
    resolvable = [impacts[p.source_id] for p in papers if p.source_id in impacts]

    top_share: float | None = None
    if cutoff is not None and resolvable:
        top_share = sum(1 for v in resolvable if v >= cutoff) / len(resolvable)

    return MemberMetrics(
        author_id=author_id,
        horizon=horizon,
        pubs=len(papers),
        led=led,
        lead_share=led / len(papers),
        citations=sum(p.cited_by_count for p in papers),
        h_index=h_index(p.cited_by_count for p in papers),
        venue_impact_median=statistics.median(resolvable) if resolvable else None,
        top_quartile_share=top_share,
    )


def top_quartile_cutoff(
    papers: Iterable[Work], impacts: Mapping[str, float]
) -> float | None:
    """The venue impact a paper has to reach to count as top-quartile.

    Computed once, from every headline-window paper the cohort wrote, and then
    held fixed across horizons. A cutoff recomputed per horizon would move under
    the comparison, so "top quartile at year 3" and "top quartile at year 6"
    would not mean the same thing.

    Within the cohort, never from a global journal list: a first-quartile
    journal in one subfield is a fourth-quartile journal in another, and the
    whole point is to describe this subfield.
    """
    values = [impacts[p.source_id] for p in papers if p.source_id in impacts]
    if len(values) < 4:
        return None
    return float(np.percentile(values, 75))


# ---------------------------------------------------------- pure: the cohort


def bootstrap_quartiles(
    values: Sequence[float],
    metric: str,
    horizon: int,
    *,
    iterations: int = 2000,
    min_cell_size: int = 5,
    rng: np.random.Generator | None = None,
) -> Quartiles:
    """Quartiles across people, with a cluster bootstrap for the uncertainty.

    Resampling people rather than papers is what makes the interval honest: the
    thing that varies between imaginable cohorts is which people are in them.
    """
    usable = [float(v) for v in values if v is not None]
    n = len(usable)
    if n < max(1, min_cell_size):
        return Quartiles(metric=metric, horizon=horizon, n=n, suppressed=True)

    sample = np.asarray(usable, dtype=float)
    p25, p50, p75 = (float(np.percentile(sample, q)) for q in (25, 50, 75))

    rng = rng or np.random.default_rng(0)
    draws = rng.integers(0, n, size=(iterations, n))
    resampled = sample[draws]
    boot = np.percentile(resampled, [25, 50, 75], axis=1)
    lo = np.percentile(boot, CI_LOW, axis=1)
    hi = np.percentile(boot, CI_HIGH, axis=1)

    return Quartiles(
        metric=metric,
        horizon=horizon,
        n=n,
        p25=p25,
        p50=p50,
        p75=p75,
        p25_lo=float(lo[0]),
        p25_hi=float(hi[0]),
        p50_lo=float(lo[1]),
        p50_hi=float(hi[1]),
        p75_lo=float(lo[2]),
        p75_hi=float(hi[2]),
    )


def benchmark_table(
    per_member: Mapping[int, Sequence[MemberMetrics]],
    config: Config,
    *,
    rng: np.random.Generator | None = None,
) -> list[Quartiles]:
    """Quartiles for every metric at every horizon."""
    rows: list[Quartiles] = []
    for horizon in sorted(per_member):
        people = per_member[horizon]
        for metric in METRICS:
            rows.append(
                bootstrap_quartiles(
                    [m.value(metric.key) for m in people],
                    metric.key,
                    horizon,
                    iterations=config.cohort.bootstrap_iterations,
                    min_cell_size=config.cohort.min_cell_size,
                    rng=rng,
                )
            )
    return rows


# -------------------------------------------------------------------- network


def fetch_venue_impacts(
    client: OpenAlexClient,
    source_ids: Iterable[str],
    *,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, float]:
    """Venue impact per source, from `summary_stats.2yr_mean_citedness`.

    Missing values stay missing. Imputing a venue impact would invent a number
    for exactly the venues OpenAlex knows least about, and those are
    disproportionately the smaller and newer journals.
    """
    wanted = sorted({s for s in source_ids if s})
    impacts: dict[str, float] = {}
    if not wanted:
        return impacts

    if on_progress:
        on_progress(f"Looking up {len(wanted)} venues.")

    for start in range(0, len(wanted), SOURCE_BATCH):
        batch = wanted[start : start + SOURCE_BATCH]
        page = client.get(
            "/sources",
            {
                "filter": "ids.openalex:" + "|".join(batch),
                "select": SOURCES_SELECT,
                "per-page": SOURCE_BATCH,
            },
        )
        for raw in page.get("results") or []:
            source_id = str(raw.get("id") or "").rstrip("/").rsplit("/", 1)[-1].upper()
            value = (raw.get("summary_stats") or {}).get("2yr_mean_citedness")
            if source_id and isinstance(value, (int, float)) and not isinstance(value, bool):
                impacts[source_id] = float(value)
    if on_progress:
        on_progress(f"  {len(impacts)} of {len(wanted)} venues have an impact figure.")
    return impacts


# --------------------------------------------------------------------- writers


def _format(value: float | None, metric: Metric) -> str:
    if value is None:
        return ""
    return f"{value:.{metric.decimals}f}"


def _metric_by_key(key: str) -> Metric:
    for metric in METRICS:
        if metric.key == key:
            return metric
    raise KeyError(key)


def write_benchmarks_csv(rows: Sequence[Quartiles], path: str | Path) -> Path:
    """The machine-readable table, counts only, guardrail enforced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "career_year",
                "metric",
                "people",
                "p25",
                "p50",
                "p75",
                "p25_ci_low",
                "p25_ci_high",
                "p50_ci_low",
                "p50_ci_high",
                "p75_ci_low",
                "p75_ci_high",
            ]
        )
        for row in rows:
            metric = _metric_by_key(row.metric)
            if row.suppressed:
                writer.writerow([row.horizon, row.metric, row.n, *[""] * 9])
                continue
            writer.writerow(
                [
                    row.horizon,
                    row.metric,
                    row.n,
                    _format(row.p25, metric),
                    _format(row.p50, metric),
                    _format(row.p75, metric),
                    _format(row.p25_lo, metric),
                    _format(row.p25_hi, metric),
                    _format(row.p50_lo, metric),
                    _format(row.p50_hi, metric),
                    _format(row.p75_lo, metric),
                    _format(row.p75_hi, metric),
                ]
            )
    assert_aggregates_only(path)
    return path


def write_benchmarks_md(
    rows: Sequence[Quartiles],
    path: str | Path,
    *,
    config: Config,
    cohort_size: int,
    institutions: int | None = None,
) -> Path:
    """The readable table, one section per metric, with the caveats attached."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    label = config.subfield.label
    lines = [
        f"# Publication norms through the tenure clock: {label}",
        "",
        f"Cohort: {cohort_size} people in {label}, each estimated to have begun a "
        f"first independent faculty appointment between {config.cohort.start_window[0]} "
        f"and {config.cohort.start_window[1]}.",
    ]
    if institutions:
        lines.append(f"They sit at {institutions} institutions.")
    lines += [
        "",
        "Every figure is a quartile across people, not an average, and the "
        "interval in brackets is a 95% confidence interval from a cluster "
        "bootstrap that resamples people rather than papers.",
        "",
        "These numbers describe what a group of people did. They are not a "
        "standard, and nobody in this cohort agreed to be measured.",
        "",
    ]

    if cohort_size < 40:
        lines += [
            f"> **Read these as indicative only.** {cohort_size} people is a small "
            "cohort, and the quartiles move a lot when the group is this size. "
            "The intervals show how much.",
            "",
        ]

    by_metric: dict[str, list[Quartiles]] = {}
    for row in rows:
        by_metric.setdefault(row.metric, []).append(row)

    for metric in METRICS:
        found = sorted(by_metric.get(metric.key, []), key=lambda r: r.horizon)
        if not found:
            continue
        lines += [
            f"## {metric.label}",
            "",
            "| Career year | People | p25 | Median | p75 |",
            "|---|---|---|---|---|",
        ]
        for row in found:
            if row.suppressed:
                lines.append(
                    f"| {row.horizon} | {row.n} | withheld | withheld | withheld |"
                )
                continue
            cells = []
            for value, lo, hi in (
                (row.p25, row.p25_lo, row.p25_hi),
                (row.p50, row.p50_lo, row.p50_hi),
                (row.p75, row.p75_lo, row.p75_hi),
            ):
                cells.append(
                    f"{_format(value, metric)} "
                    f"[{_format(lo, metric)} to {_format(hi, metric)}]"
                )
            lines.append(f"| {row.horizon} | {row.n} | " + " | ".join(cells) + " |")
        lines.append("")

    lines += [
        "## What these numbers do not cover",
        "",
        "Teaching, mentoring, service, funding, software, datasets, and public "
        "scholarship are not in OpenAlex and are a large part of the job.",
        "",
        "Citations are counted as they stand today, so a paper from career year 1 "
        "has had longer to collect them than one from year 6. Compare citation "
        "figures between people at the same career year and the same calendar "
        "distance from now, or not at all.",
        "",
        "Venue impact is `2yr_mean_citedness` from OpenAlex, and top-quartile "
        "means top quartile within this cohort's own venues, not a global list. "
        "Venues with no impact figure are left out of that calculation rather "
        "than counted as zero.",
        "",
        "Cells covering fewer than "
        f"{config.cohort.min_cell_size} people are withheld, because a quartile "
        "over a handful of people can identify them.",
        "",
        "Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, 2022), "
        "CC0.",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    assert_aggregates_only(path)
    return path


# ------------------------------------------------------------- orchestration


def build_metrics(
    works_by_member: Mapping[str, Sequence[Work]],
    starts: Mapping[str, StartEstimate],
    config: Config,
    impacts: Mapping[str, float],
    *,
    horizons: Sequence[int] | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[dict[int, list[MemberMetrics]], list[Quartiles], float | None, list[Work]]:
    """Metrics per person per horizon, the quartile table, the venue cutoff, and
    the window papers the cutoff and the venue list are both built from."""
    horizons = tuple(horizons or config.cohort.horizons)
    article_types = config.cohort.article_types
    headline = max(horizons)

    headline_papers = [
        paper
        for author_id, works in works_by_member.items()
        if starts.get(author_id) and starts[author_id].year
        for paper in window_papers(
            works, starts[author_id].year or 0, headline, article_types
        )
    ]
    cutoff = top_quartile_cutoff(headline_papers, impacts)

    per_member: dict[int, list[MemberMetrics]] = {}
    for horizon in horizons:
        rows = []
        for author_id, works in works_by_member.items():
            estimate = starts.get(author_id)
            if estimate is None or estimate.year is None:
                continue
            rows.append(
                member_metrics(
                    works,
                    [author_id],
                    estimate.year,
                    horizon,
                    article_types,
                    impacts,
                    cutoff,
                )
            )
        per_member[horizon] = rows

    return (
        per_member,
        benchmark_table(per_member, config, rng=rng),
        cutoff,
        headline_papers,
    )


def collect_member_works(
    client: OpenAlexClient,
    asked: Sequence[str],
    wanted: Iterable[str],
    config: Config,
    *,
    data_dir: str | Path = "data",
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, list[Work]]:
    """The cohort's papers, read from the file task 4 wrote.

    Task 4 already downloaded these, so refetching would be pure waste. It
    cannot be avoided by leaning on the request cache alone: works are fetched
    fifty authors per query and a cached page is keyed by the exact batch, so
    removing a single candidate shifts every later batch and invalidates all of
    it. Measured: excluding the subject from his own pool turned a free replay
    into 1,236 requests.

    Falling back to the network keeps this usable if `data/` was cleared while
    `.cache/` survived.
    """
    keep = {a.upper() for a in wanted}
    stored = Path(data_dir) / WORKS_FILENAME

    if stored.exists():
        collected = load_works(stored, keep)
        if collected:
            if on_progress:
                on_progress(
                    f"Read papers for {len(collected)} cohort members from "
                    f"{stored} (no requests)."
                )
            return collected

    window = config.cohort.start_window
    first_year = window[0] - TRAINEE_LOOKBACK_YEARS
    last_year = window[1] + config.cohort.horizon_years
    if on_progress:
        on_progress(f"Fetching papers for {len(keep)} cohort members.")

    collected = {}
    for author_id, works in fetch_works_by_author(
        client, list(asked), first_year, last_year
    ):
        if author_id.upper() in keep:
            collected[author_id] = list(works)
    if on_progress:
        on_progress(
            f"  {sum(len(w) for w in collected.values())} papers "
            f"({client.request_count} requests so far)."
        )
    return collected


def build_benchmarks(
    client: OpenAlexClient,
    members: Sequence[tuple],
    asked: Sequence[str],
    config: Config,
    *,
    data_dir: str | Path = "data",
    results_dir: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    rng: np.random.Generator | None = None,
) -> BenchmarkResult:
    """The whole of task 5: papers, venues, metrics, quartiles, two files."""
    results = Path(results_dir) if results_dir is not None else config.output.dir
    starts = {candidate.author_id: estimate for candidate, estimate in members}

    works_by_member = collect_member_works(
        client, asked, starts, config, data_dir=data_dir, on_progress=on_progress
    )
    impacts = fetch_venue_impacts(
        client,
        (w.source_id for works in works_by_member.values() for w in works),
        on_progress=on_progress,
    )
    per_member, rows, cutoff, headline_papers = build_metrics(
        works_by_member, starts, config, impacts, rng=rng
    )

    institutions = len(
        {
            estimate.institution_ror
            for _, estimate in members
            if estimate.institution_ror
        }
    )
    csv_path = write_benchmarks_csv(rows, results / BENCHMARKS_CSV)
    md_path = write_benchmarks_md(
        rows,
        results / BENCHMARKS_MD,
        config=config,
        cohort_size=len(members),
        institutions=institutions,
    )
    if on_progress:
        on_progress(f"Wrote {csv_path} and {md_path}.")
    return BenchmarkResult(
        per_member=per_member,
        rows=rows,
        impacts=impacts,
        cutoff=cutoff,
        works_by_member=works_by_member,
        headline_papers=headline_papers,
        institutions=institutions,
        csv_path=csv_path,
        md_path=md_path,
    )
