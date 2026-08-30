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
import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tenuretrack.config import Config
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.pool import Candidate, Funnel
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
    "StaleStarts",
    "StartEstimate",
    "build_starts",
    "candidates_worth_asking",
    "estimate_start",
    "estimate_starts",
    "load_starts",
    "read_fingerprint",
    "starts_fingerprint",
    "load_works",
    "plausible_years",
    "screen_starts",
]

STARTS_FILENAME = "starts.jsonl.gz"

STARTS_META_FILENAME = "starts.meta.json"
"""What the estimates in `STARTS_FILENAME` were built from.

The estimates file is reused whole whenever it exists, which is what makes a
run that died on quota restartable for nothing. But it is keyed by its
filename and nothing else, so a config edited between two runs used to be
answered out of a file built under the old config, silently: people newly
eligible under a wider window had no entry, and `screen_starts` drops anyone
without one without a word. This records the inputs so the reuse can be
refused instead.
"""

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


class StaleStarts(RuntimeError):
    """Cached career starts were built under rules the current config changed.

    Raised rather than quietly re-estimating, because re-estimating is the
    most expensive stage in the pipeline and spending a few thousand requests
    of somebody's daily budget is their decision to make, not this function's.
    """


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


def starts_fingerprint(author_ids: Sequence[str], config: Config) -> dict:
    """Everything that decides what ends up in the estimates file.

    The people are recorded as a hash of the sorted IDs rather than as a list,
    because the file lives beside a pool that holds names and a list of author
    IDs is one of the things the aggregates-only rule keeps out of anything
    shareable. A count travels with it so a mismatch can be described.
    """
    ids = sorted({a.upper() for a in author_ids if a})
    digest = hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest()
    return {
        "start_window": list(config.cohort.start_window),
        "horizon_years": config.cohort.horizon_years,
        "article_types": list(config.cohort.article_types),
        "excluded_venues": list(config.cohort.excluded_venues),
        "people": len(ids),
        "people_hash": digest,
    }


def read_fingerprint(path: str | Path) -> dict | None:
    """The fingerprint beside an estimates file, or None if there is not one."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def describe_drift(old: Mapping, new: Mapping) -> str:
    """Name what changed between two fingerprints, in the config's own words."""
    if old.get("start_window") != new.get("start_window"):
        was, now = old.get("start_window"), new.get("start_window")
        return (
            f"the cohort window is now {_window_words(now)}, and the saved "
            f"estimates were built for {_window_words(was)}"
        )
    if old.get("horizon_years") != new.get("horizon_years"):
        return (
            f"horizon_years is now {new.get('horizon_years')}, and the saved "
            f"estimates were built for {old.get('horizon_years')}, which changes "
            "how many years of papers were asked for"
        )
    for key in ("article_types", "excluded_venues"):
        if old.get(key) != new.get(key):
            return (
                f"cohort.{key} changed, and every start was estimated from the "
                "papers the old setting left in"
            )
    if old.get("people_hash") != new.get("people_hash"):
        return (
            f"the screening now asks about {new.get('people')} people and the "
            f"saved estimates cover {old.get('people')}, so a filter earlier in "
            "the funnel changed"
        )
    return ""


def _window_words(window: object) -> str:
    if isinstance(window, (list, tuple)) and len(window) == 2:
        return f"{window[0]} to {window[1]}"
    return str(window)


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
    window = config.cohort.start_window
    first_year = window[0] - TRAINEE_LOOKBACK_YEARS
    last_year = window[1] + config.cohort.horizon_years
    author_ids = [c.author_id for c in candidates if c.author_id]
    meta_path = dest.parent / STARTS_META_FILENAME
    fingerprint = starts_fingerprint(author_ids, config)

    if dest.exists() and not refresh:
        saved = read_fingerprint(meta_path)
        if saved is None:
            # Written before this check existed. Reused rather than refused,
            # because refusing would charge a full re-estimate to everyone
            # holding a file from an earlier version.
            if on_progress:
                on_progress(
                    f"Career starts already estimated at {dest}. There is no "
                    f"{STARTS_META_FILENAME} beside it, so what they were built "
                    "from cannot be checked. If the cohort window or any filter "
                    "changed since, rerun with --refresh."
                )
            return load_starts(dest)
        drift = describe_drift(saved, fingerprint)
        if drift:
            raise StaleStarts(
                f"{dest} cannot be reused: {drift}. Reusing it would leave "
                "every newly eligible person without an estimate, and they are "
                "dropped without a word. Rerun with --refresh to estimate "
                f"again, which refetches all {len(author_ids)} people because a "
                "batch is cached under the exact set of IDs in it, or put the "
                "old setting back to carry on with what is already downloaded."
            )
        if on_progress:
            on_progress(f"Career starts already estimated at {dest}.")
        return load_starts(dest)

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
    meta_path.write_text(
        json.dumps(fingerprint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
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
    candidates: Sequence[Candidate], start_window: tuple[int, int]
) -> list[Candidate]:
    """The people whose works are worth fetching, in a stable order.

    Later stages replay the same batched works queries out of the cache, and a
    batch is keyed by the exact set of author IDs in it. Recomputing this list
    the same way is what makes those replays free rather than a second full
    download.
    """
    return [c for c in candidates if plausible_years(c, start_window)]


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
    worth_asking = candidates_worth_asking(candidates, window)
    funnel.record(
        "plausible years",
        f"byline years could contain a start between {window[0]} and {window[1]}",
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
