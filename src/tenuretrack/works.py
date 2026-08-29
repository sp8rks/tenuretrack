"""Work records, and what one person's line on a paper means.

Shared by the subject (task 2), career-start estimation (task 4), the metrics
(task 5), and the chaperone analysis (task 7). It lives in one module because
the rules have to be identical on both sides of every comparison: a benchmark
where the subject's papers are counted by one definition of "journal article"
and the cohort's by another is not a benchmark.

Nothing here writes anything. Parsing and classification are pure functions,
and the two fetchers are thin wrappers over the cached client.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

from tenuretrack.openalex import OpenAlexClient

__all__ = [
    "Byline",
    "LED",
    "FIRST_NOT_LED",
    "MIDDLE",
    "PREPRINT_SOURCE_TYPES",
    "WORKS_SELECT",
    "Work",
    "fetch_works",
    "fetch_works_by_author",
    "bylines_of",
    "has_byline_at",
    "institutions_on",
    "is_excluded_venue",
    "is_journal_article",
    "only_bylines_of",
    "parse_work",
    "work_from_row",
    "work_to_row",
    "role_of",
    "short_author_id",
    "short_source_id",
    "short_topic_id",
]

WORKS_SELECT = (
    "id,doi,title,publication_year,type,authorships,primary_location,"
    "primary_topic,cited_by_count"
)

PREPRINT_SOURCE_TYPES = frozenset({"repository"})

LED = "led"
FIRST_NOT_LED = "first_not_led"
MIDDLE = "middle"
"""Author roles. See `.claude/skills/cohort-methodology`.

`led` is last author or flagged corresponding: the paper came out of this
person's group. `first_not_led` is first author on someone else's paper, which
is what a trainee looks like. Everything else is `middle`.
"""

BATCH_SIZE = 50
"""Author IDs per works query. OpenAlex takes up to 50 values in one OR filter.

Batching does not reduce how many work records come back, but it removes the
per-author request floor, which on a cohort of thousands is most of the cost.
"""

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Byline:
    """One person's line on one paper."""

    author_id: str
    position: str = ""
    is_corresponding: bool = False
    institution_rors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Work:
    """The parts of an OpenAlex work this tool actually reads."""

    id: str
    year: int
    doi: str = ""
    title: str = ""
    type: str = ""
    source_id: str = ""
    source_name: str = ""
    source_type: str = ""
    topic_id: str = ""
    topic_name: str = ""
    topic_subfield: str = ""
    cited_by_count: int = 0
    bylines: tuple[Byline, ...] = ()

    @property
    def key(self) -> str:
        """Identity for unioning split profiles.

        The DOI when there is one. Otherwise a normalized title plus year,
        which catches the same paper appearing under two author IDs and is
        conservative enough not to merge two different papers.
        """
        if self.doi:
            return self.doi
        return f"{normalize_title(self.title)}|{self.year}"


def work_to_row(work: Work) -> dict:
    """The on-disk shape, explicit so the file survives a refactor."""
    return {
        "id": work.id,
        "y": work.year,
        "doi": work.doi,
        "t": work.title,
        "ty": work.type,
        "s": work.source_id,
        "sn": work.source_name,
        "st": work.source_type,
        "tp": work.topic_id,
        "tn": work.topic_name,
        "tf": work.topic_subfield,
        "c": work.cited_by_count,
        "b": [
            [b.author_id, b.position, int(b.is_corresponding), list(b.institution_rors)]
            for b in work.bylines
        ],
    }


def work_from_row(row) -> Work:
    return Work(
        id=str(row.get("id") or ""),
        year=int(row.get("y") or 0),
        doi=str(row.get("doi") or ""),
        title=str(row.get("t") or ""),
        type=str(row.get("ty") or ""),
        source_id=str(row.get("s") or ""),
        source_name=str(row.get("sn") or ""),
        source_type=str(row.get("st") or ""),
        topic_id=str(row.get("tp") or ""),
        topic_name=str(row.get("tn") or ""),
        topic_subfield=str(row.get("tf") or ""),
        cited_by_count=int(row.get("c") or 0),
        bylines=tuple(
            Byline(
                author_id=str(b[0]),
                position=str(b[1]),
                is_corresponding=bool(b[2]),
                institution_rors=tuple(str(r) for r in b[3]),
            )
            for b in row.get("b") or []
        ),
    )


def only_bylines_of(work: Work, author_ids: Iterable[str]) -> Work:
    """The same paper with every other author's line dropped.

    A materials paper can carry fifty authorships and we only ever read this
    person's: their position, their corresponding flag, their institutions.
    Keeping the rest would multiply the stored record by an order of magnitude
    for data no stage looks at.
    """
    return replace(work, bylines=bylines_of(work, author_ids))


# -------------------------------------------------------------------- parsing


def parse_work(raw) -> Work:
    """Trim an OpenAlex work down to the fields this tool reads."""
    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    topic = raw.get("primary_topic") or {}
    subfield = (topic.get("subfield") or {}).get("display_name") or ""

    bylines = []
    for authorship in raw.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        author_id = short_author_id(author.get("id"))
        if not author_id:
            continue
        rors = tuple(
            str(inst.get("ror"))
            for inst in (authorship.get("institutions") or [])
            if isinstance(inst, dict) and inst.get("ror")
        )
        bylines.append(
            Byline(
                author_id=author_id,
                position=str(authorship.get("author_position") or ""),
                is_corresponding=bool(authorship.get("is_corresponding")),
                institution_rors=rors,
            )
        )

    year = raw.get("publication_year")
    return Work(
        id=str(raw.get("id") or ""),
        year=int(year) if isinstance(year, int) and not isinstance(year, bool) else 0,
        doi=normalize_doi(raw.get("doi")),
        title=str(raw.get("title") or ""),
        type=str(raw.get("type") or ""),
        source_id=short_source_id(source.get("id")),
        source_name=str(source.get("display_name") or ""),
        source_type=str(source.get("type") or ""),
        topic_id=short_topic_id(topic.get("id")),
        topic_name=str(topic.get("display_name") or ""),
        topic_subfield=str(subfield),
        cited_by_count=int(raw.get("cited_by_count") or 0),
        bylines=tuple(bylines),
    )


def normalize_title(title: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", (title or "").lower())).strip()


def normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text.rsplit("doi.org/", 1)[-1]


def short_author_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"A\d+", text) else ""


def short_topic_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"T\d+", text) else ""


def short_source_id(value: object) -> str:
    """`https://openalex.org/S12345` to `S12345`, the form filters take."""
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"S\d+", text) else ""


def short_ror(value: object) -> str:
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()


# ------------------------------------------------------------------ filtering


def is_excluded_venue(work: Work, excluded: Iterable[str]) -> bool:
    """Is this paper in a venue the config asks to leave out?

    Matched on OpenAlex source ID or on the exact display name, case-insensitive,
    so a config can name a venue the way a person would read it.
    """
    wanted = {e.strip().lower() for e in excluded if e and e.strip()}
    if not wanted:
        return False
    return (
        work.source_id.lower() in wanted or work.source_name.strip().lower() in wanted
    )


def is_journal_article(
    work: Work, article_types: Sequence[str], excluded_venues: Iterable[str] = ()
) -> bool:
    """A journal article, not a preprint, editorial, chapter, or erratum.

    The same rule runs on the subject and on every cohort member, because a
    comparison where one side counts preprints is not a comparison. The same is
    true of `excluded_venues`: it is applied to both sides or to neither.
    """
    if work.type not in set(article_types):
        return False
    if work.source_type in PREPRINT_SOURCE_TYPES:
        return False
    return not is_excluded_venue(work, excluded_venues)


def has_byline_at(work: Work, author_ids: Iterable[str], ror: str) -> bool:
    """Did this person carry that institution's byline on this paper?"""
    wanted = {a.upper() for a in author_ids}
    want_ror = short_ror(ror)
    for byline in work.bylines:
        if byline.author_id.upper() not in wanted:
            continue
        if any(short_ror(r) == want_ror for r in byline.institution_rors):
            return True
    return False


def bylines_of(work: Work, author_ids: Iterable[str]) -> tuple[Byline, ...]:
    """Every line this person (or their merged profiles) has on this paper."""
    wanted = {a.upper() for a in author_ids}
    return tuple(b for b in work.bylines if b.author_id.upper() in wanted)


def role_of(work: Work, author_ids: Iterable[str]) -> str:
    """Led, first-not-led, or middle. Empty when the person is not on the paper.

    Corresponding-author flags are missing for many journal-years, so last
    position is the robust signal and the flag is a bonus. Where merged
    profiles put the same person on a paper twice, the strongest role wins.
    """
    found = bylines_of(work, author_ids)
    if not found:
        return ""
    if any(b.position == "last" or b.is_corresponding for b in found):
        return LED
    if any(b.position == "first" for b in found):
        return FIRST_NOT_LED
    return MIDDLE


def institutions_on(work: Work, author_ids: Iterable[str]) -> tuple[str, ...]:
    """The RORs this person carried on this paper, normalized."""
    out: list[str] = []
    for byline in bylines_of(work, author_ids):
        for ror in byline.institution_rors:
            short = short_ror(ror)
            if short and short not in out:
                out.append(short)
    return tuple(out)


# -------------------------------------------------------------------- fetching


def _year_filter(first_year: int, last_year: int) -> str:
    return f"publication_year:{first_year}-{last_year}"


def fetch_works(
    client: OpenAlexClient,
    author_ids: Sequence[str],
    first_year: int,
    last_year: int,
) -> list[Work]:
    """Every work by any of these author IDs, unioned by DOI.

    For one person whose record is split across profiles. The cohort uses
    `fetch_works_by_author`, which keeps the people apart.
    """
    unioned: dict[str, Work] = {}
    for author_id in author_ids:
        filters = f"authorships.author.id:{author_id},{_year_filter(first_year, last_year)}"
        for raw in client.paginate("/works", {"filter": filters, "select": WORKS_SELECT}):
            work = parse_work(raw)
            if work.year:
                unioned.setdefault(work.key, work)
    return sorted(unioned.values(), key=lambda w: (-w.year, w.title, w.id))


def fetch_works_by_author(
    client: OpenAlexClient,
    author_ids: Sequence[str],
    first_year: int,
    last_year: int,
    *,
    batch_size: int = BATCH_SIZE,
) -> Iterator[tuple[str, list[Work]]]:
    """Yield `(author_id, works)` for thousands of people, batched.

    One query per author would put a floor of one request per person on a stage
    that runs over a whole cohort. Asking for fifty at a time drops the request
    count to roughly the number of pages the results actually fill.

    A paper co-authored by two people in the batch is yielded to both, which is
    correct: it is on both of their records.
    """
    for start in range(0, len(author_ids), batch_size):
        batch = [a for a in author_ids[start : start + batch_size] if a]
        if not batch:
            continue
        filters = (
            "authorships.author.id:"
            + "|".join(batch)
            + f",{_year_filter(first_year, last_year)}"
        )
        collected: dict[str, dict[str, Work]] = {a: {} for a in batch}
        wanted = set(batch)
        for raw in client.paginate("/works", {"filter": filters, "select": WORKS_SELECT}):
            work = parse_work(raw)
            if not work.year:
                continue
            for byline in work.bylines:
                if byline.author_id in wanted:
                    collected[byline.author_id].setdefault(work.key, work)
        for author_id in batch:
            works = sorted(
                collected[author_id].values(), key=lambda w: (w.year, w.title, w.id)
            )
            yield author_id, works
