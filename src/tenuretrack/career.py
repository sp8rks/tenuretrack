"""Estimate when each candidate started their first independent job (task 4).

The cohort is people at the same point on the tenure clock, so every candidate
needs a start year. The subject supplies theirs and it is trusted. For everyone
else it has to be inferred from bylines, and the inference is the weakest link
in the whole method: a wrong start year moves someone to the wrong career year
and quietly corrupts the norms. So the rule is deliberately strict, and anyone
it cannot place confidently is dropped and counted rather than guessed at.

The rules are `docs/methods.md` section 5. Rule 1 there is the ORCID employment
record, which is authoritative and which OpenAlex does not carry: an author
record has `affiliations` with years derived from bylines, and nothing about
appointments. Checked against the live API, so rule 1 never fires and the code
does not pretend to implement it. What runs is rule 2 (high confidence) and
rule 3 (low confidence, and low confidence does not enter the cohort).

Estimates hold author IDs, so they are written under `data/` and never to
`results/`.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tenuretrack.config import Config
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.pool import Candidate, Funnel, core_topic_share
from tenuretrack.works import (
    LED,
    Work,
    fetch_works_by_author,
    institutions_on,
    is_journal_article,
    only_bylines_of,
    role_of,
    work_from_row,
    work_to_row,
)

__all__ = [
    "AFFILIATION_LED",
    "FIRST_LED_MINUS_ONE",
    "HIGH",
    "LOW",
    "NO_RULE",
    "StartEstimate",
    "build_starts",
    "cap_cutoff",
    "candidates_worth_asking",
    "estimate_start",
    "estimate_starts",
    "load_starts",
    "load_works",
    "plausible_years",
    "screen_starts",
]

STARTS_FILENAME = "starts.jsonl.gz"

WORKS_FILENAME = "works.jsonl.gz"
"""Everyone's papers, kept so later stages never refetch them.

The request cache alone is not enough. Works are fetched fifty authors at a
time and a cached page is keyed by the exact set of IDs in its batch, so adding
or removing one candidate shifts every batch after them and invalidates the
lot. Measured: excluding the subject from his own pool turned what should have
been a free replay into 1,236 requests. Writing the papers out by author
decouples the later stages from how the fetch happened to be grouped.

Only the person's own byline is kept on each paper. A materials paper can carry
fifty authorships and no stage reads anyone else's. Holds author IDs, so it
lives under `data/`.
"""

AFFILIATION_LED = "affiliation_led"
FIRST_LED_MINUS_ONE = "first_led_minus_one"
NO_RULE = "none"

HIGH = "high"
LOW = "low"

MIN_LED_AT_INSTITUTION = 2
"""Led papers needed at an institution before it counts as an independent post.

One led paper is a fluke of author ordering. Two at the same place, after
arriving there, is the shape of running a group. This is a floor, not the whole
test: see `PRINCIPAL_LED_SHARE`.
"""

PRINCIPAL_LED_SHARE = 0.2
"""How much of a person's led output an institution must hold to be a real post.

A flat two-paper bar treats a stray affiliation as equal evidence to a career.
Measured case: a subject with 71 led papers at his university also carried two
at a nearby medical center, and the flat rule picked the medical center. Judging
each institution against the person's own strongest post fixes that without any
absolute number, which would not travel across fields.
"""

TRAINEE_LOOKBACK_YEARS = 15
"""Years before the cohort window to fetch, so the PhD and postdoc years are
visible. Rule 2 infers the trainee institution from them."""

PROGRESS_BLOCK = 20
"""Batches between progress lines."""


@dataclass(frozen=True, slots=True)
class StartEstimate:
    """One person's estimated first independent start, and how sure we are."""

    author_id: str
    year: int | None = None
    rule: str = NO_RULE
    confidence: str = LOW
    institution_ror: str = ""
    led_papers: int = 0
    note: str = ""

    @property
    def is_usable(self) -> bool:
        """Only a high-confidence estimate may put someone in the cohort."""
        return self.year is not None and self.confidence == HIGH

    def to_row(self) -> dict:
        return {
            "author_id": self.author_id,
            "year": self.year,
            "rule": self.rule,
            "confidence": self.confidence,
            "institution_ror": self.institution_ror,
            "led_papers": self.led_papers,
            "note": self.note,
        }

    @classmethod
    def from_row(cls, row: Mapping) -> StartEstimate:
        return cls(
            author_id=str(row.get("author_id") or ""),
            year=row.get("year"),
            rule=str(row.get("rule") or NO_RULE),
            confidence=str(row.get("confidence") or LOW),
            institution_ror=str(row.get("institution_ror") or ""),
            led_papers=int(row.get("led_papers") or 0),
            note=str(row.get("note") or ""),
        )


# ----------------------------------------------------------------- pure: rules


def estimate_start(
    works: Sequence[Work],
    author_ids: Sequence[str],
    article_types: Sequence[str],
    excluded_venues: Sequence[str] = (),
) -> StartEstimate:
    """Estimate the first independent start from one person's papers.

    Rule 2: find the institutions that look like independent posts, meaning
    they hold at least two of the person's led papers and at least a fifth of
    however many they led at their strongest post. Take the earliest of those
    by first byline year, and accept it only when some earlier institution was
    not itself a post. That earlier institution is the PhD or postdoc, and its
    absence is what makes the estimate ambiguous: someone whose whole record
    sits at one place could be a faculty member who never moved, or a student
    who stayed.

    Rule 3: the first led paper minus one. Always low confidence, so it never
    puts anyone in the cohort. It exists so the funnel can say how many people
    were placed weakly rather than not at all.
    """
    author_id = author_ids[0] if author_ids else ""
    articles = [
        w
        for w in works
        if is_journal_article(w, article_types, excluded_venues) and w.year
    ]
    if not articles:
        return StartEstimate(author_id, note="no journal articles on record")

    first_seen: dict[str, int] = {}
    led_years: dict[str, list[int]] = {}
    led_anywhere: list[int] = []

    for work in articles:
        role = role_of(work, author_ids)
        for ror in institutions_on(work, author_ids):
            if ror not in first_seen or work.year < first_seen[ror]:
                first_seen[ror] = work.year
            if role == LED:
                led_years.setdefault(ror, []).append(work.year)
        if role == LED:
            led_anywhere.append(work.year)

    # An institution counts as an independent post only if it holds a real share
    # of this person's led output, judged against their strongest post. Two
    # papers alone is a stray affiliation as often as it is a job.
    principal = max((len(y) for y in led_years.values()), default=0)
    floor = max(MIN_LED_AT_INSTITUTION, PRINCIPAL_LED_SHARE * principal)
    posts = {ror: years for ror, years in led_years.items() if len(years) >= floor}

    # Earliest first: a person who moved between two faculty jobs started at the
    # first one.
    qualifying = sorted(
        ((first_seen[ror], ror, len(years)) for ror, years in posts.items()),
        key=lambda item: (item[0], item[1]),
    )
    for year, ror, count in qualifying:
        # The trainee years are anywhere earlier that was not itself a post. It
        # is not enough to look for an institution with no led papers at all:
        # one last-author paper during a PhD would hide the real start.
        trainee = [
            other
            for other, seen in first_seen.items()
            if other != ror and seen < year and other not in posts
        ]
        if trainee:
            return StartEstimate(
                author_id=author_id,
                year=year,
                rule=AFFILIATION_LED,
                confidence=HIGH,
                institution_ror=ror,
                led_papers=count,
            )

    if qualifying:
        year, ror, count = qualifying[0]
        return StartEstimate(
            author_id=author_id,
            year=year,
            rule=AFFILIATION_LED,
            confidence=LOW,
            institution_ror=ror,
            led_papers=count,
            note="no earlier institution that was not itself an independent "
            "post, so the trainee years cannot be told apart from them",
        )

    if led_anywhere:
        return StartEstimate(
            author_id=author_id,
            year=min(led_anywhere) - 1,
            rule=FIRST_LED_MINUS_ONE,
            confidence=LOW,
            led_papers=len(led_anywhere),
            note="no institution holds enough of their led papers to look "
            "like a post of their own",
        )

    return StartEstimate(
        author_id=author_id, note="no led papers, so no independent post to date"
    )


def plausible_years(candidate: Candidate, start_window: tuple[int, int]) -> bool:
    """Could this person's record hold a usable start inside the window?

    A cheap check against the affiliation years already in the pool, so people
    who cannot pass anyway do not cost a works request. It is deliberately weak:
    it only drops people whose rule-2 estimate could not land in the window, so
    it saves requests without changing who ends up in the cohort.

    Someone whose first byline is after the window closed cannot have a rule-2
    start inside it, because rule 2 never returns a year before their first
    paper. Someone whose last byline is before the window opened cannot either.
    """
    years = [y for a in candidate.affiliations for y in a.years]
    if not years:
        return False
    return min(years) <= start_window[1] and max(years) >= start_window[0]


# --------------------------------------------------------------------- storage


def estimate_starts(
    client: OpenAlexClient,
    candidates: Sequence[Candidate],
    config: Config,
    dest: str | Path,
    *,
    on_progress: Callable[[str], None] | None = None,
    refresh: bool = False,
) -> dict[str, StartEstimate]:
    """Fetch every candidate's papers in batches and estimate their start.

    This is the long stage. Works are asked for fifty authors at a time, so the
    request count tracks the number of pages the results fill rather than the
    number of people.
    """
    dest = Path(dest)
    if dest.exists() and not refresh:
        if on_progress:
            on_progress(f"Career starts already estimated at {dest}.")
        return load_starts(dest)

    window = config.cohort.start_window
    first_year = window[0] - TRAINEE_LOOKBACK_YEARS
    last_year = window[1] + config.cohort.horizon_years
    author_ids = [c.author_id for c in candidates if c.author_id]

    if on_progress:
        batches = -(-len(author_ids) // 50)
        on_progress(
            f"Estimating career starts for {len(author_ids)} people "
            f"({batches} batched queries, papers from {first_year} to {last_year})."
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    works_dest = dest.parent / WORKS_FILENAME
    works_tmp = works_dest.with_suffix(works_dest.suffix + ".tmp")
    estimates: dict[str, StartEstimate] = {}
    done = 0

    with gzip.open(tmp, "wt", encoding="utf-8") as handle, gzip.open(
        works_tmp, "wt", encoding="utf-8"
    ) as works_handle:
        for author_id, works in fetch_works_by_author(
            client, author_ids, first_year, last_year
        ):
            estimate = estimate_start(
                works,
                [author_id],
                config.cohort.article_types,
                config.cohort.excluded_venues,
            )
            estimates[author_id] = estimate
            handle.write(
                json.dumps(estimate.to_row(), separators=(",", ":")) + "\n"
            )
            works_handle.write(
                json.dumps(
                    {
                        "author_id": author_id,
                        "works": [
                            work_to_row(only_bylines_of(w, [author_id])) for w in works
                        ],
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            done += 1
            if on_progress and done % (PROGRESS_BLOCK * 50) == 0:
                on_progress(
                    f"  {done} of {len(author_ids)} placed, "
                    f"{client.request_count} requests"
                )

    os.replace(tmp, dest)
    os.replace(works_tmp, works_dest)
    if on_progress:
        on_progress(
            f"Career starts estimated for {done} people "
            f"({client.request_count} requests)."
        )
    return estimates


def load_works(
    path: str | Path, wanted: Iterable[str] | None = None
) -> dict[str, list[Work]]:
    """Read the papers back, optionally only for the people still of interest."""
    keep = None if wanted is None else {a.upper() for a in wanted}
    out: dict[str, list[Work]] = {}
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            author_id = str(row.get("author_id") or "")
            if keep is not None and author_id.upper() not in keep:
                continue
            out[author_id] = [work_from_row(w) for w in row.get("works") or []]
    return out


def load_starts(path: str | Path) -> dict[str, StartEstimate]:
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        rows = (json.loads(line) for line in handle if line.strip())
        return {
            estimate.author_id: estimate
            for estimate in (StartEstimate.from_row(row) for row in rows)
        }


# ------------------------------------------------------------------ screening


def screen_starts(
    candidates: Iterable[Candidate],
    estimates: Mapping[str, StartEstimate],
    config: Config,
    funnel: Funnel,
) -> list[tuple[Candidate, StartEstimate]]:
    """Keep people placed confidently inside the cohort window, counting as we go."""
    window = config.cohort.start_window
    placed = 0
    kept: list[tuple[Candidate, StartEstimate]] = []

    for candidate in candidates:
        estimate = estimates.get(candidate.author_id)
        if estimate is None or not estimate.is_usable:
            continue
        placed += 1
        if window[0] <= (estimate.year or 0) <= window[1]:
            kept.append((candidate, estimate))

    funnel.record(
        "career start estimated",
        f"a confident first independent start (at least "
        f"{MIN_LED_AT_INSTITUTION} led papers at one institution, with earlier "
        f"trainee years elsewhere)",
        placed,
    )
    funnel.record(
        "start in window",
        f"estimated start between {window[0]} and {window[1]}",
        len(kept),
    )
    return kept


def candidates_worth_asking(
    candidates: Sequence[Candidate], config: Config
) -> list[Candidate]:
    """The people whose works are worth fetching, in a stable order.

    Two things happen here. Anyone whose byline years could not contain a start
    inside the window is dropped, which removes only people the rule would have
    dropped anyway and so saves requests without changing the cohort. Then the
    rest are ranked by their share of work in the subfield and cut to
    `cohort.max_candidates`.

    The cut is the same selection as raising `core_topic_share_min` until the
    count fits, and `cap_cutoff` reports the share it landed on so the funnel
    can say it in the config's own vocabulary. It is what bounds the run: this
    is the stage that asks OpenAlex about every person individually, and on one
    measured subject it was 4,141 people and most of the wall time.

    The order is stable, and deliberately so. Later stages replay the same
    batched works queries out of the cache, a batch is keyed by the exact set
    of author IDs in it, and one person moving between batches invalidates
    every batch after them. Ties on share are broken by author ID for the same
    reason.
    """
    eligible = [c for c in candidates if plausible_years(c, config.cohort.start_window)]
    limit = config.cohort.max_candidates
    if limit <= 0 or len(eligible) <= limit:
        return eligible
    topic_ids = config.subfield.topic_ids
    ranked = sorted(
        eligible,
        key=lambda c: (-core_topic_share(c, topic_ids), c.author_id.upper()),
    )
    return ranked[:limit]


def cap_cutoff(kept: Sequence[Candidate], config: Config) -> float | None:
    """The core-topic share of the last person the cap let in.

    None when the cap did not bind, so a caller can tell "everyone who passed
    the filters" from "the most on-topic 2,000 of them".
    """
    if config.cohort.max_candidates <= 0 or len(kept) < config.cohort.max_candidates:
        return None
    topic_ids = config.subfield.topic_ids
    return min(core_topic_share(c, topic_ids) for c in kept) if kept else None


def build_starts(
    client: OpenAlexClient,
    candidates: Sequence[Candidate],
    config: Config,
    funnel: Funnel,
    *,
    data_dir: str | Path = "data",
    on_progress: Callable[[str], None] | None = None,
    refresh: bool = False,
) -> list[tuple[Candidate, StartEstimate]]:
    """Pre-filter, estimate, and screen. The whole of task 4."""
    window = config.cohort.start_window
    plausible = [c for c in candidates if plausible_years(c, window)]
    funnel.record(
        "plausible years",
        f"byline years could contain a start between {window[0]} and {window[1]}",
        len(plausible),
    )

    worth_asking = candidates_worth_asking(candidates, config)
    cutoff = cap_cutoff(worth_asking, config)
    if cutoff is not None:
        funnel.record(
            "most on topic",
            f"the {config.cohort.max_candidates} candidates with the largest "
            f"share of work in the subfield, which is a share of at least "
            f"{cutoff:.2f} here, raised from "
            f"{config.cohort.core_topic_share_min} to fit cohort.max_candidates",
            len(worth_asking),
        )

    estimates = estimate_starts(
        client,
        worth_asking,
        config,
        Path(data_dir) / STARTS_FILENAME,
        on_progress=on_progress,
        refresh=refresh,
    )
    return screen_starts(worth_asking, estimates, config, funnel)
