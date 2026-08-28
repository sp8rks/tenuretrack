"""Build the candidate pool and run the first funnel filters (TASKS.md task 3).

The pool is everyone OpenAlex lists with real output in the configured topics,
in the configured countries. That set is large and noisy: it holds graduate
students, staff scientists, industrial researchers, emeritus professors, and
people whose work only glances off the subfield. Later tasks narrow it to
early-career faculty. This one gathers it, writes it to `data/` where names are
allowed to live, and applies the two filters that do not need any per-paper
data: core-topic share, and holding a university affiliation.

Every count the funnel records goes to `results/funnel.csv`, which is how a
reader checks that the cohort is sensible. That file holds counts and nothing
else, and the guardrail runs on it before this module returns.

Names in this module stay inside `data/`. Nothing here writes a name, an
OpenAlex ID, or an ORCID into `results/`.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tenuretrack.config import Config
from tenuretrack.guardrail import assert_aggregates_only
from tenuretrack.openalex import OpenAlexClient

__all__ = [
    "Affiliation",
    "Candidate",
    "Funnel",
    "FunnelStep",
    "PoolResult",
    "TopicShare",
    "build_pool",
    "core_topic_share",
    "estimate_pool_size",
    "harvest_pool",
    "has_university_affiliation",
    "in_countries",
    "load_pool",
    "parse_candidate",
    "pool_filter",
    "screen_pool",
]

POOL_FILENAME = "pool.jsonl.gz"
FUNNEL_FILENAME = "funnel.csv"

MIN_WORKS = 10
"""Authors below this have too little record to place on a tenure clock, and
they are most of what a topic filter returns. Dropping them at the API keeps
the pool an order of magnitude smaller."""

POOL_SELECT = (
    "id,display_name,orcid,affiliations,last_known_institutions,topics,"
    "summary_stats,works_count,cited_by_count"
)

PROGRESS_BLOCK = 2000
"""Candidates between progress lines. A large subfield runs to tens of
thousands, and a stage with no output looks hung."""


# ---------------------------------------------------------------- data shapes


@dataclass(frozen=True, slots=True)
class Affiliation:
    ror: str
    name: str = ""
    country_code: str = ""
    type: str = ""
    years: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TopicShare:
    id: str
    count: int = 0
    share: float | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One person in the pool.

    `name` and `orcid` live here because career-start estimation and the
    identity filter need them, and because `show-cohort` prints them for the
    maintainer's own sanity check. They stay under `data/`.
    """

    author_id: str
    name: str = ""
    orcid: str = ""
    works_count: int = 0
    cited_by_count: int = 0
    h_index: int = 0
    topics: tuple[TopicShare, ...] = ()
    affiliations: tuple[Affiliation, ...] = ()

    def to_row(self) -> dict:
        """The on-disk shape. Explicit so the file survives a refactor."""
        return {
            "author_id": self.author_id,
            "name": self.name,
            "orcid": self.orcid,
            "works_count": self.works_count,
            "cited_by_count": self.cited_by_count,
            "h_index": self.h_index,
            "topics": [
                {"id": t.id, "count": t.count, "share": t.share} for t in self.topics
            ],
            "affiliations": [
                {
                    "ror": a.ror,
                    "name": a.name,
                    "country_code": a.country_code,
                    "type": a.type,
                    "years": list(a.years),
                }
                for a in self.affiliations
            ],
        }

    @classmethod
    def from_row(cls, row: Mapping) -> Candidate:
        return cls(
            author_id=str(row.get("author_id") or ""),
            name=str(row.get("name") or ""),
            orcid=str(row.get("orcid") or ""),
            works_count=int(row.get("works_count") or 0),
            cited_by_count=int(row.get("cited_by_count") or 0),
            h_index=int(row.get("h_index") or 0),
            topics=tuple(
                TopicShare(
                    id=str(t.get("id") or ""),
                    count=int(t.get("count") or 0),
                    share=t.get("share"),
                )
                for t in row.get("topics") or []
            ),
            affiliations=tuple(
                Affiliation(
                    ror=str(a.get("ror") or ""),
                    name=str(a.get("name") or ""),
                    country_code=str(a.get("country_code") or ""),
                    type=str(a.get("type") or ""),
                    years=tuple(int(y) for y in (a.get("years") or [])),
                )
                for a in row.get("affiliations") or []
            ),
        )


@dataclass(frozen=True)
class FunnelStep:
    """One row of `results/funnel.csv`. Counts only, never people."""

    step: int
    label: str
    rule: str
    kept: int
    dropped: int


@dataclass
class Funnel:
    """The running count of who is left after each filter."""

    steps: list[FunnelStep] = field(default_factory=list)

    @property
    def current(self) -> int:
        return self.steps[-1].kept if self.steps else 0

    def record(self, label: str, rule: str, kept: int) -> FunnelStep:
        previous = self.current if self.steps else kept
        step = FunnelStep(
            step=len(self.steps) + 1,
            label=label,
            rule=rule,
            kept=kept,
            dropped=max(0, previous - kept),
        )
        self.steps.append(step)
        return step

    def write_csv(self, path: str | Path) -> Path:
        """Write the funnel, then prove it carries nothing but counts."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["step", "label", "rule", "kept", "dropped"])
            for step in self.steps:
                writer.writerow(
                    [step.step, step.label, step.rule, step.kept, step.dropped]
                )
        assert_aggregates_only(path)
        return path


@dataclass(frozen=True)
class PoolResult:
    pool_size: int
    kept: tuple[Candidate, ...]
    funnel: Funnel
    pool_path: Path
    funnel_path: Path


# ------------------------------------------------------------- pure: parsing


def parse_candidate(raw: Mapping) -> Candidate:
    """Trim an OpenAlex author record to what the funnel and metrics read."""
    stats = raw.get("summary_stats") or {}
    return Candidate(
        author_id=_short_id(raw.get("id"), "A"),
        name=str(raw.get("display_name") or ""),
        orcid=str(raw.get("orcid") or "").rstrip("/").rsplit("/", 1)[-1],
        works_count=int(raw.get("works_count") or 0),
        cited_by_count=int(raw.get("cited_by_count") or 0),
        h_index=int(stats.get("h_index") or 0),
        topics=tuple(
            TopicShare(
                id=_short_id((t or {}).get("id"), "T"),
                count=int((t or {}).get("count") or 0),
                share=_optional_float((t or {}).get("share")),
            )
            for t in (raw.get("topics") or [])
            if _short_id((t or {}).get("id"), "T")
        ),
        affiliations=tuple(_affiliation(a) for a in (raw.get("affiliations") or [])),
    )


def _affiliation(raw: Mapping) -> Affiliation:
    institution = (raw or {}).get("institution") or {}
    return Affiliation(
        ror=str(institution.get("ror") or "").rstrip("/").rsplit("/", 1)[-1],
        name=str(institution.get("display_name") or ""),
        country_code=str(institution.get("country_code") or "").upper(),
        type=str(institution.get("type") or "").lower(),
        years=tuple(
            int(y) for y in (raw.get("years") or []) if isinstance(y, int)
        ),
    )


def _short_id(value: object, prefix: str) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if text.startswith(prefix) and text[1:].isdigit() else ""


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ------------------------------------------------------------ pure: filtering


def core_topic_share(candidate: Candidate, topic_ids: Iterable[str]) -> float:
    """How much of this person's work sits in the configured subfield.

    OpenAlex gives a `share` per topic on newer author records. Where it is
    missing, the same quantity is computed from the work counts, which is what
    `share` is derived from anyway. A person with no topics at all scores zero
    rather than raising: they simply do not clear the filter.
    """
    wanted = {t.upper() for t in topic_ids}
    if not candidate.topics:
        return 0.0

    if all(t.share is not None for t in candidate.topics):
        total = sum(t.share or 0.0 for t in candidate.topics)
        if total > 0:
            core = sum(t.share or 0.0 for t in candidate.topics if t.id in wanted)
            return core / total

    total_count = sum(t.count for t in candidate.topics)
    if total_count <= 0:
        return 0.0
    return sum(t.count for t in candidate.topics if t.id in wanted) / total_count


def has_university_affiliation(
    candidate: Candidate, institution_types: Iterable[str]
) -> bool:
    """At least one affiliation of a configured type, normally `education`.

    Someone who holds both a national-lab and a university appointment stays.
    Someone with only industry, government, or hospital affiliations does not,
    because they are not on a tenure clock.
    """
    wanted = {t.lower() for t in institution_types}
    return any(a.type in wanted for a in candidate.affiliations)


def in_countries(candidate: Candidate, countries: Iterable[str]) -> bool:
    """Any affiliation in the configured countries.

    The API filter already asked for this, so it normally passes. It runs again
    locally because a cached pool may predate a config change.
    """
    wanted = {c.upper() for c in countries}
    return any(a.country_code in wanted for a in candidate.affiliations)


def pool_filter(
    topic_ids: Sequence[str],
    countries: Sequence[str],
    min_works: int = MIN_WORKS,
) -> str:
    """The OpenAlex author filter that defines the pool.

    `|` is OR inside one filter, `,` is AND across filters, so this reads as
    "any of these topics, and at least one affiliation in any of these
    countries, and more than `min_works - 1` works".
    """
    if not topic_ids:
        raise ValueError("a candidate pool needs at least one topic")
    parts = [
        "topics.id:" + "|".join(t.upper() for t in topic_ids),
        f"works_count:>{max(0, min_works - 1)}",
    ]
    if countries:
        parts.append(
            "affiliations.institution.country_code:"
            + "|".join(c.upper() for c in countries)
        )
    return ",".join(parts)


# -------------------------------------------------------------------- storage


def estimate_pool_size(
    client: OpenAlexClient,
    topic_ids: Sequence[str],
    countries: Sequence[str],
    min_works: int = MIN_WORKS,
) -> int:
    """How many people the pool query will return, in one request.

    Gathering a large subfield takes tens of minutes, so it is worth one cheap
    request to say up front how long it is going to be.
    """
    page = client.get(
        "/authors",
        {
            "filter": pool_filter(topic_ids, countries, min_works),
            "per-page": 1,
            "select": "id",
        },
    )
    return int((page.get("meta") or {}).get("count") or 0)


def harvest_pool(
    client: OpenAlexClient,
    topic_ids: Sequence[str],
    countries: Sequence[str],
    dest: str | Path,
    *,
    min_works: int = MIN_WORKS,
    on_progress: Callable[[str], None] | None = None,
    refresh: bool = False,
) -> int:
    """Page through the pool and write it, gzipped, one candidate per line.

    Written to a temporary file and renamed, so a file that exists is a file
    that finished. A rerun after a quota stop replays the cached pages and
    costs no requests.
    """
    dest = Path(dest)
    if dest.exists() and not refresh:
        if on_progress:
            on_progress(f"Candidate pool already gathered at {dest}.")
        return sum(1 for _ in load_pool(dest))

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    seen: set[str] = set()
    written = 0

    filters = pool_filter(topic_ids, countries, min_works)
    if on_progress:
        expected = estimate_pool_size(client, topic_ids, countries, min_works)
        pages = -(-expected // 200)  # ceiling, at the client's page size
        on_progress(f"Gathering candidates: {filters}")
        on_progress(f"About {expected} people to gather, roughly {pages} pages.")

    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for raw in client.paginate(
            "/authors", {"filter": filters, "select": POOL_SELECT}
        ):
            candidate = parse_candidate(raw)
            if not candidate.author_id or candidate.author_id in seen:
                continue
            seen.add(candidate.author_id)
            handle.write(json.dumps(candidate.to_row(), separators=(",", ":")) + "\n")
            written += 1
            if on_progress and written % PROGRESS_BLOCK == 0:
                on_progress(
                    f"  {written} candidates so far, "
                    f"{client.request_count} requests"
                )

    os.replace(tmp, dest)
    if on_progress:
        on_progress(f"Candidate pool: {written} people ({client.request_count} requests).")
    return written


def load_pool(path: str | Path) -> Iterator[Candidate]:
    """Stream a gathered pool back off disk. A pool can be large; do not list it."""
    path = Path(path)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield Candidate.from_row(json.loads(line))


# ------------------------------------------------------------------ screening


def screen_pool(
    candidates: Iterable[Candidate], config: Config, funnel: Funnel
) -> list[Candidate]:
    """Apply the funnel steps that need no per-paper data, counting as it goes.

    The steps run in the order `docs/methods.md` lists them, and each records
    its own count, because a funnel that only reports the final number tells a
    reader nothing about which filter did the work.
    """
    cohort = config.cohort
    topic_ids = config.subfield.topic_ids

    in_country = on_topic = 0
    kept: list[Candidate] = []

    # One streaming pass. A pool runs to tens of thousands of people, and
    # filtering it in stages would hold every one of them in memory to build a
    # list that the next stage immediately throws most of away.
    for person in candidates:
        # The API filter already asked for the country, so this normally
        # removes nobody. It runs anyway because a pool gathered under one
        # config can be re-screened under another without refetching.
        if not in_countries(person, cohort.countries):
            continue
        in_country += 1
        if core_topic_share(person, topic_ids) < cohort.core_topic_share_min:
            continue
        on_topic += 1
        if not has_university_affiliation(person, cohort.institution_types):
            continue
        kept.append(person)

    funnel.record(
        "candidates",
        f"topics {'|'.join(topic_ids)}, at least {MIN_WORKS} works, "
        f"an affiliation in {'|'.join(cohort.countries)}",
        in_country,
    )
    funnel.record(
        "core topic share",
        f"share of work in the subfield at least {cohort.core_topic_share_min}",
        on_topic,
    )
    funnel.record(
        "university",
        f"an affiliation of type {'|'.join(cohort.institution_types)}",
        len(kept),
    )
    return kept


def build_pool(
    client: OpenAlexClient,
    config: Config,
    *,
    data_dir: str | Path = "data",
    results_dir: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    refresh: bool = False,
) -> PoolResult:
    """Gather the pool, screen it, and write the funnel."""
    data_dir = Path(data_dir)
    results = Path(results_dir) if results_dir is not None else config.output.dir
    pool_path = data_dir / POOL_FILENAME

    size = harvest_pool(
        client,
        config.subfield.topic_ids,
        config.cohort.countries,
        pool_path,
        on_progress=on_progress,
        refresh=refresh,
    )

    funnel = Funnel()
    kept = screen_pool(load_pool(pool_path), config, funnel)
    funnel_path = funnel.write_csv(results / FUNNEL_FILENAME)

    if on_progress:
        on_progress(f"Wrote {funnel_path}.")
    return PoolResult(
        pool_size=size,
        kept=tuple(kept),
        funnel=funnel,
        pool_path=pool_path,
        funnel_path=funnel_path,
    )
