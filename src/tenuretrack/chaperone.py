"""Do people publish in better venues when they are not leading? (task 7)

Sekara et al., "The chaperone effect in scientific publishing" (PNAS 2018,
doi 10.1073/pnas.1800471115), found that a researcher's route into a prestigious
venue often runs through a senior co-author rather than through their own group.
This asks the same question of one subfield cohort: for the same people, in the
same window, does a paper they led land in a top-quartile venue as often as a
paper they merely appear on?

This is a cross-sectional approximation of their design, not a replication.
Sekara et al. followed authors longitudinally and modelled the sequence of a
career. Here every cohort member's window is a single snapshot, and the
comparison is within-person across roles rather than across time. The direction
of an effect is informative; its size is not directly comparable to theirs.

Two readings of the same data are reported because either alone misleads. The
pooled rate answers "across all the cohort's papers, which role reaches better
venues", and is dominated by whoever wrote the most papers. The paired
within-person comparison answers "for a typical person, which role reaches
better venues", and drops anyone without enough papers in both roles. Where
they disagree, the disagreement is the finding.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tenuretrack.career import StartEstimate
from tenuretrack.config import Config
from tenuretrack.guardrail import assert_aggregates_only
from tenuretrack.metrics import window_papers
from tenuretrack.works import FIRST_NOT_LED, LED, MIDDLE, Work, role_of

__all__ = [
    "CHAPERONE_CSV",
    "CHAPERONE_MD",
    "Gap",
    "PairedTest",
    "PersonRoles",
    "RoleRate",
    "build_chaperone",
    "led_vs_middle_gap",
    "paired_within_person",
    "person_roles",
    "pooled_rates",
    "sign_test",
    "venue_coauthored_share",
    "write_chaperone_csv",
    "write_chaperone_md",
]

CHAPERONE_CSV = "chaperone.csv"
CHAPERONE_MD = "chaperone.md"

ROLES = (LED, FIRST_NOT_LED, MIDDLE)
ROLE_LABELS = {
    LED: "Led (last or corresponding)",
    FIRST_NOT_LED: "First author, not leading",
    MIDDLE: "Middle author",
}

MIN_PAPERS_PER_ROLE = 3
"""Venue-resolvable papers needed in both roles to enter the paired comparison.

Below three, one paper flips a person's within-person share from 0 to 1 and the
sign test starts counting coin flips.
"""

BOOTSTRAP_CI = (2.5, 97.5)


@dataclass(frozen=True, slots=True)
class PersonRoles:
    """One person's venue-resolvable window papers, split by role. Stays in `data/`."""

    author_id: str
    led_papers: int = 0
    led_top: int = 0
    first_papers: int = 0
    first_top: int = 0
    middle_papers: int = 0
    middle_top: int = 0

    def papers(self, role: str) -> int:
        return {
            LED: self.led_papers,
            FIRST_NOT_LED: self.first_papers,
            MIDDLE: self.middle_papers,
        }[role]

    def top(self, role: str) -> int:
        return {LED: self.led_top, FIRST_NOT_LED: self.first_top, MIDDLE: self.middle_top}[
            role
        ]

    def share(self, role: str) -> float | None:
        n = self.papers(role)
        return self.top(role) / n if n else None


@dataclass(frozen=True, slots=True)
class RoleRate:
    """How often papers in one role reached a top-quartile venue, pooled."""

    role: str
    people: int
    papers: int
    top_quartile: int
    rate: float | None


@dataclass(frozen=True, slots=True)
class Gap:
    """Middle-author rate minus led rate, with a cluster-bootstrap interval."""

    led_rate: float | None
    middle_rate: float | None
    gap: float | None
    lo: float | None
    hi: float | None
    people: int


@dataclass(frozen=True, slots=True)
class PairedTest:
    """The within-person comparison, for people with papers in both roles."""

    people: int
    median_led_share: float | None
    median_middle_share: float | None
    higher_on_middle: int
    higher_on_led: int
    ties: int
    p_value: float | None


# ------------------------------------------------------------ pure: counting


def person_roles(
    works: Sequence[Work],
    author_id: str,
    start_year: int,
    horizon: int,
    article_types: Sequence[str],
    impacts: Mapping[str, float],
    cutoff: float | None,
    excluded_venues: Sequence[str] = (),
) -> PersonRoles:
    """Split one person's window papers by role, counting top-quartile venues.

    Only papers whose venue has an impact figure are counted, on both sides.
    Counting a paper in the denominator whose venue we cannot place would make
    the rate depend on how well OpenAlex covers the venues a person happened to
    use, which differs systematically by role.
    """
    counts = {role: [0, 0] for role in ROLES}
    if cutoff is None:
        return PersonRoles(author_id=author_id)

    for paper in window_papers(
        works, start_year, horizon, article_types, excluded_venues
    ):
        impact = impacts.get(paper.source_id)
        if impact is None:
            continue
        role = role_of(paper, [author_id])
        if role not in counts:
            continue
        counts[role][0] += 1
        if impact >= cutoff:
            counts[role][1] += 1

    return PersonRoles(
        author_id=author_id,
        led_papers=counts[LED][0],
        led_top=counts[LED][1],
        first_papers=counts[FIRST_NOT_LED][0],
        first_top=counts[FIRST_NOT_LED][1],
        middle_papers=counts[MIDDLE][0],
        middle_top=counts[MIDDLE][1],
    )


def pooled_rates(people: Sequence[PersonRoles]) -> list[RoleRate]:
    """Top-quartile rate per role across every paper in the cohort.

    Pooled over papers, so a prolific member counts more than a quiet one. That
    is the right reading of "across this subfield's output" and the wrong
    reading of "for a typical person", which is what the paired test is for.
    """
    out = []
    for role in ROLES:
        papers = sum(p.papers(role) for p in people)
        top = sum(p.top(role) for p in people)
        out.append(
            RoleRate(
                role=role,
                people=sum(1 for p in people if p.papers(role) > 0),
                papers=papers,
                top_quartile=top,
                rate=top / papers if papers else None,
            )
        )
    return out


def led_vs_middle_gap(
    people: Sequence[PersonRoles],
    *,
    iterations: int = 2000,
    rng: np.random.Generator | None = None,
) -> Gap:
    """The pooled middle-minus-led gap, with people resampled for the interval.

    Resampling people rather than papers again: the uncertainty that matters is
    which people are in the cohort, not which of one person's papers landed.
    """
    usable = [p for p in people if p.led_papers or p.middle_papers]
    if not usable:
        return Gap(None, None, None, None, None, 0)

    def rates(sample: Sequence[PersonRoles]) -> tuple[float | None, float | None]:
        led_n = sum(p.led_papers for p in sample)
        mid_n = sum(p.middle_papers for p in sample)
        led = sum(p.led_top for p in sample) / led_n if led_n else None
        mid = sum(p.middle_top for p in sample) / mid_n if mid_n else None
        return led, mid

    led_rate, middle_rate = rates(usable)
    if led_rate is None or middle_rate is None:
        return Gap(led_rate, middle_rate, None, None, None, len(usable))

    rng = rng or np.random.default_rng(0)
    n = len(usable)
    gaps: list[float] = []
    for _ in range(iterations):
        draw = [usable[i] for i in rng.integers(0, n, size=n)]
        led, mid = rates(draw)
        if led is not None and mid is not None:
            gaps.append(mid - led)

    lo, hi = (
        (float(np.percentile(gaps, BOOTSTRAP_CI[0])), float(np.percentile(gaps, BOOTSTRAP_CI[1])))
        if gaps
        else (None, None)
    )
    return Gap(
        led_rate=led_rate,
        middle_rate=middle_rate,
        gap=middle_rate - led_rate,
        lo=lo,
        hi=hi,
        people=n,
    )


def sign_test(higher: int, lower: int) -> float | None:
    """Two-sided sign test on paired outcomes, ties already dropped.

    Written out rather than pulled from scipy: it is eight lines, and adding a
    dependency for one p-value is not worth it.
    """
    n = higher + lower
    if n == 0:
        return None
    k = min(higher, lower)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def paired_within_person(
    people: Sequence[PersonRoles], *, min_papers: int = MIN_PAPERS_PER_ROLE
) -> PairedTest:
    """Compare each person against themselves, then count who went which way.

    Only people with enough venue-resolvable papers in both roles. This removes
    every between-person difference at once: field, institution, career stage,
    and how prolific someone is all cancel when a person is their own control.
    """
    paired = [
        p
        for p in people
        if p.led_papers >= min_papers and p.middle_papers >= min_papers
    ]
    if not paired:
        return PairedTest(0, None, None, 0, 0, 0, None)

    led_shares = [p.share(LED) or 0.0 for p in paired]
    middle_shares = [p.share(MIDDLE) or 0.0 for p in paired]

    higher_middle = sum(1 for a, b in zip(led_shares, middle_shares, strict=True) if b > a)
    higher_led = sum(1 for a, b in zip(led_shares, middle_shares, strict=True) if a > b)
    ties = len(paired) - higher_middle - higher_led

    return PairedTest(
        people=len(paired),
        median_led_share=statistics.median(led_shares),
        median_middle_share=statistics.median(middle_shares),
        higher_on_middle=higher_middle,
        higher_on_led=higher_led,
        ties=ties,
        p_value=sign_test(higher_middle, higher_led),
    )


def venue_coauthored_share(
    works_by_member: Mapping[str, Sequence[Work]],
    starts: Mapping[str, StartEstimate],
    config: Config,
    *,
    limit: int = 15,
) -> list[tuple[str, int, float | None]]:
    """For the busiest venues, how much of the cohort's output there was led.

    Names venues, never people. A venue where the cohort rarely leads is one it
    reaches largely as somebody else's co-author.
    """
    papers: Counter[str] = Counter()
    led: Counter[str] = Counter()
    names: dict[str, str] = {}

    for author_id, works in works_by_member.items():
        estimate = starts.get(author_id)
        if estimate is None or estimate.year is None:
            continue
        for paper in window_papers(
            works,
            estimate.year,
            config.cohort.horizon_years,
            config.cohort.article_types,
            config.cohort.excluded_venues,
        ):
            if not paper.source_id:
                continue
            papers[paper.source_id] += 1
            names.setdefault(paper.source_id, paper.source_name or paper.source_id)
            if role_of(paper, [author_id]) == LED:
                led[paper.source_id] += 1

    return [
        (
            names.get(source_id, source_id),
            count,
            led[source_id] / count if count else None,
        )
        for source_id, count in papers.most_common(limit)
    ]


# --------------------------------------------------------------------- writers


def _pct(value: float | None) -> str:
    return "" if value is None else f"{value:.1%}"


def write_chaperone_csv(
    rates: Sequence[RoleRate],
    gap: Gap,
    paired: PairedTest,
    venues: Sequence[tuple[str, int, float | None]],
    path: str | Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", "key", "people", "papers", "value", "low", "high"])
        for rate in rates:
            writer.writerow(
                ["pooled_rate", rate.role, rate.people, rate.papers,
                 "" if rate.rate is None else f"{rate.rate:.4f}", "", ""]
            )
        writer.writerow(
            ["gap", "middle_minus_led", gap.people, "",
             "" if gap.gap is None else f"{gap.gap:.4f}",
             "" if gap.lo is None else f"{gap.lo:.4f}",
             "" if gap.hi is None else f"{gap.hi:.4f}"]
        )
        writer.writerow(
            ["paired", "median_led_share", paired.people, "",
             "" if paired.median_led_share is None else f"{paired.median_led_share:.4f}",
             "", ""]
        )
        writer.writerow(
            ["paired", "median_middle_share", paired.people, "",
             "" if paired.median_middle_share is None else f"{paired.median_middle_share:.4f}",
             "", ""]
        )
        writer.writerow(
            ["paired", "sign_test_p", paired.people, "",
             "" if paired.p_value is None else f"{paired.p_value:.6f}", "", ""]
        )
        for name, count, led_share in venues:
            writer.writerow(
                ["venue", name, "", count,
                 "" if led_share is None else f"{led_share:.4f}", "", ""]
            )
    assert_aggregates_only(path)
    return path


def write_chaperone_md(
    rates: Sequence[RoleRate],
    gap: Gap,
    paired: PairedTest,
    venues: Sequence[tuple[str, int, float | None]],
    path: str | Path,
    *,
    config: Config,
    cohort_size: int,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    label = config.subfield.label

    lines = [
        f"# Led versus co-authored papers in {label}",
        "",
        f"For {cohort_size} people in {label}, through career year "
        f"{config.cohort.horizon_years}: when a paper reached a top-quartile "
        "venue, was this person leading it?",
        "",
        "Roles follow the last-author convention. Led means last author or "
        "flagged corresponding author. First-author-not-leading is the shape of "
        "a paper written inside somebody else's group. Middle is everything "
        "else. Only papers whose venue has an impact figure are counted, on "
        "every side.",
        "",
        "## Across all the cohort's papers",
        "",
        "| Role | People | Papers | In top-quartile venues | Rate |",
        "|---|---|---|---|---|",
    ]
    for rate in rates:
        lines.append(
            f"| {ROLE_LABELS[rate.role]} | {rate.people} | {rate.papers} | "
            f"{rate.top_quartile} | {_pct(rate.rate)} |"
        )

    lines += ["", "## Middle-author rate minus led rate", ""]
    if gap.gap is None:
        lines.append("Too few papers in one of the roles to compare.")
    else:
        lines += [
            f"{_pct(gap.gap)} (95% CI {_pct(gap.lo)} to {_pct(gap.hi)}), across "
            f"{gap.people} people.",
            "",
            "A positive number means the cohort's papers reached top-quartile "
            "venues more often when its members were not leading them. The "
            "interval comes from a cluster bootstrap resampling people, so it "
            "describes how much this would move with a different draw of people "
            "from the same subfield.",
        ]

    lines += ["", "## The same people, compared against themselves", ""]
    if paired.people == 0:
        lines.append(
            f"Nobody had at least {MIN_PAPERS_PER_ROLE} venue-resolvable papers "
            "in both roles, so there is no paired comparison."
        )
    else:
        direction = (
            "more often when not leading"
            if paired.higher_on_middle > paired.higher_on_led
            else "more often when leading"
        )
        lines += [
            f"{paired.people} people had at least {MIN_PAPERS_PER_ROLE} "
            "venue-resolvable papers in both roles.",
            "",
            "| | Median within-person rate |",
            "|---|---|",
            f"| Papers they led | {_pct(paired.median_led_share)} |",
            f"| Papers they did not lead | {_pct(paired.median_middle_share)} |",
            "",
            f"{paired.higher_on_middle} reached top-quartile venues {direction}, "
            f"{paired.higher_on_led} the other way, {paired.ties} the same. "
            f"Sign test p = {paired.p_value:.4g}."
            if paired.p_value is not None
            else "",
            "",
            "Every person here is their own control, so field, institution, "
            "career stage and how prolific someone is all cancel out.",
        ]

    lines += [
        "",
        "## Where the cohort leads and where it does not",
        "",
        "| Venue | Cohort papers | Share the cohort led |",
        "|---|---|---|",
    ]
    for name, count, led_share in venues:
        lines.append(f"| {name} | {count} | {_pct(led_share)} |")

    lines += [
        "",
        "## What this is and is not",
        "",
        "This follows Sekara, Deville, Andersen, Jones, Lehmann and Ahmadpoor, "
        '"The chaperone effect in scientific publishing", PNAS 2018 '
        "(doi 10.1073/pnas.1800471115), which found that a researcher's route "
        "into a prestigious venue often runs through a senior co-author.",
        "",
        "It is an approximation of their design, not a replication. They "
        "followed authors through time and modelled the sequence of a career. "
        "Here each person's window is one snapshot and the comparison is across "
        "roles within it. The direction of a difference is informative; its "
        "size should not be read against their figures.",
        "",
        "Corresponding-author flags are missing for many journals and years, so "
        "last position carries most of the weight in deciding who led. Where a "
        "field does not order authors by contribution, none of this applies.",
        "",
        "The two readings above answer different questions. The pooled rate is "
        "dominated by whoever wrote the most papers; the paired comparison "
        "describes a typical person but drops anyone without papers in both "
        "roles. Where they disagree, that disagreement is the finding.",
        "",
        "Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, "
        "2022), CC0.",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    assert_aggregates_only(path)
    return path


# ------------------------------------------------------------- orchestration


def build_chaperone(
    benchmarks,
    starts: Mapping[str, StartEstimate],
    config: Config,
    *,
    results_dir: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[Path, Path, Gap, PairedTest]:
    """The whole of task 7, from papers already on disk. No network."""
    results = Path(results_dir) if results_dir is not None else config.output.dir

    people = [
        person_roles(
            works,
            author_id,
            starts[author_id].year or 0,
            config.cohort.horizon_years,
            config.cohort.article_types,
            benchmarks.impacts,
            benchmarks.cutoff,
            config.cohort.excluded_venues,
        )
        for author_id, works in benchmarks.works_by_member.items()
        if starts.get(author_id) and starts[author_id].year
    ]

    rates = pooled_rates(people)
    gap = led_vs_middle_gap(
        people, iterations=config.cohort.bootstrap_iterations, rng=rng
    )
    paired = paired_within_person(people)
    venues = venue_coauthored_share(benchmarks.works_by_member, starts, config)

    csv_path = write_chaperone_csv(rates, gap, paired, venues, results / CHAPERONE_CSV)
    md_path = write_chaperone_md(
        rates, gap, paired, venues, results / CHAPERONE_MD,
        config=config, cohort_size=len(people),
    )
    if on_progress:
        on_progress(f"Wrote {csv_path.name} and {md_path.name}.")
    return csv_path, md_path, gap, paired
