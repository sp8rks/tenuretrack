"""Resolve the subject and propose the topics that define their subfield.

This is `tenuretrack init` (TASKS.md, task 2). It answers three questions with
as few OpenAlex requests as it can:

- Which OpenAlex author record is this person? From the ORCID, plus any stray
  profiles that split their work at the same institution.
- Which of their papers form the tenure-clock window? Journal articles from
  `start_year` onward carrying the institution's byline.
- Which topics describe those papers? Ranked by how many of the papers sit in
  each one, with the venues those papers ran in, so the person can look at the
  list and say whether it is really their field.

The network layer is thin and lives at the bottom of the file. Everything that
decides anything is a pure function above it, so the ranking rules are tested
with small synthetic dictionaries: no network, and no fixture carrying a real
person's name.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from tenuretrack.config import MAX_TOPICS, ROR_RE, CohortSpec, OutputSpec
from tenuretrack.openalex import OpenAlexClient, OpenAlexError, OpenAlexHTTPError
from tenuretrack.pool import estimate_pool_size

__all__ = [
    "Byline",
    "InitError",
    "InitResult",
    "Institution",
    "TopicProposal",
    "Work",
    "draft_config",
    "measure_reach",
    "fetch_works",
    "find_split_profiles",
    "format_result",
    "has_byline_at",
    "initialize",
    "is_journal_article",
    "is_split_profile",
    "parse_work",
    "propose_topics",
    "resolve_author",
    "resolve_institution",
    "select_window_works",
    "subfield_label",
]

# --------------------------------------------------------------------- tuning

AUTHORS_SELECT = (
    "id,display_name,display_name_alternatives,orcid,affiliations,topics,"
    "summary_stats,works_count"
)
WORKS_SELECT = (
    "id,doi,title,publication_year,type,authorships,primary_location,"
    "primary_topic,cited_by_count"
)
INSTITUTIONS_SELECT = "id,ror,display_name,country_code,type,works_count"

LOOKBACK_YEARS = 8
"""Fetch this many years before the appointment began.

Papers from the postdoc years are not part of the window, but they are what a
career-start estimate leans on later, and they are the fallback the topic
proposal uses when someone is early enough in the clock to have almost no
papers under the new byline yet.
"""

MIN_ANCHORED_WORKS = 5
"""Below this many institution-anchored papers, widen the topic proposal.

Anchoring on the institution byline is the rule the window uses. But someone in
career year 1 or 2 may have two papers under the new affiliation, which is too
thin to name a subfield from, so the proposal falls back to a wider set and
says so out loud rather than quietly widening.
"""

MIN_TOPIC_PAPERS = 3
RELAXED_TOPIC_PAPERS = 2
"""A topic carrying one or two papers is noise, so it is not proposed. If that
leaves fewer than `WANTED_TOPICS`, the count relaxes by one and the printout
says the record is thin."""

WANTED_TOPICS = 4
TOP_VENUES_PER_TOPIC = 3

LOPSIDED_TOPIC_SHARE = 0.4
"""Flag a topic contributing more than this much of the whole set's reach.

One topic carrying nearly half the people, while carrying a handful of the
subject's papers, is the signature of a neighboring community rather than a
subfield."""

SPLIT_MAX_WORKS = 10
SPLIT_MAX_SHARE = 0.5
"""A split profile is a fragment: few works, and clearly the smaller half. Two
profiles that both carry substantial output are two people until proven
otherwise, so they are never unioned."""

PREPRINT_SOURCE_TYPES = frozenset({"repository"})

_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md"})
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


class InitError(RuntimeError):
    """`init` cannot go on, worded for someone reading it in a browser."""


# ---------------------------------------------------------------- data shapes


@dataclass(frozen=True)
class Institution:
    ror: str
    name: str
    country_code: str = ""
    type: str = ""
    works_count: int = 0

    @property
    def short_ror(self) -> str:
        return self.ror.rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Byline:
    """One person's line on one paper."""

    author_id: str
    position: str = ""
    is_corresponding: bool = False
    institution_rors: tuple[str, ...] = ()


@dataclass(frozen=True)
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
        return f"{_normalize_title(self.title)}|{self.year}"


@dataclass(frozen=True)
class TopicProposal:
    """One proposed topic, with the evidence for proposing it."""

    id: str
    name: str
    papers: int
    subfield: str = ""
    venues: tuple[str, ...] = ()
    reach: int | None = None
    """People OpenAlex lists in this topic who could enter the cohort.

    How central a topic is to the subject says nothing about how many people it
    drags in. On one measured subject, the two topics carrying the fewest of
    their papers contributed 58,000 of an 82,601 pool. Showing this next to the
    paper count is what makes the topic choice an informed one.
    """

    def share_of(self, total: int) -> float:
        return self.papers / total if total else 0.0


@dataclass(frozen=True)
class InitResult:
    """Everything `init` learned, ready to print and ready to write."""

    subject_name: str
    author_id: str
    institution: Institution
    start_year: int
    topics: tuple[TopicProposal, ...]
    label: str
    orcid: str = ""
    alt_author_ids: tuple[str, ...] = ()
    institution_alternatives: tuple[Institution, ...] = ()
    works_seen: int = 0
    window_works: int = 0
    fetched_from: int = 0
    combined_reach: int | None = None
    basis: str = "anchored"
    current_career_year: int = 1
    notes: tuple[str, ...] = ()
    config: Mapping[str, object] = field(default_factory=dict)


# ------------------------------------------------------------ pure: filtering


def is_journal_article(work: Work, article_types: Sequence[str]) -> bool:
    """A journal article, not a preprint, editorial, chapter, or erratum.

    The same rule runs on the subject and on every cohort member, because a
    comparison where one side counts preprints is not a comparison.
    """
    if work.type not in set(article_types):
        return False
    return work.source_type not in PREPRINT_SOURCE_TYPES


def has_byline_at(work: Work, author_ids: Iterable[str], ror: str) -> bool:
    """Did this person carry that institution's byline on this paper?"""
    wanted = {a.upper() for a in author_ids}
    short = ror.rstrip("/").rsplit("/", 1)[-1].lower()
    for byline in work.bylines:
        if byline.author_id.upper() not in wanted:
            continue
        for candidate in byline.institution_rors:
            if candidate.rstrip("/").rsplit("/", 1)[-1].lower() == short:
                return True
    return False


def select_window_works(
    works: Sequence[Work],
    author_ids: Iterable[str],
    ror: str,
    start_year: int,
    article_types: Sequence[str],
) -> tuple[list[Work], str]:
    """The papers the topic proposal reads, plus which rule produced them.

    The basis comes back as `anchored`, `since_start`, or `all_years`, so the
    printout can say what it looked at.
    """
    articles = [w for w in works if is_journal_article(w, article_types)]
    since_start = [w for w in articles if w.year >= start_year]
    anchored = [w for w in since_start if has_byline_at(w, author_ids, ror)]

    if len(anchored) >= MIN_ANCHORED_WORKS:
        return anchored, "anchored"
    if since_start:
        return since_start, "since_start"
    return articles, "all_years"


# ------------------------------------------------------------- pure: proposal


def propose_topics(
    works: Sequence[Work], limit: int = MAX_TOPICS
) -> tuple[TopicProposal, ...]:
    """Rank topics by how many of these papers sit in each one.

    Each paper votes once, for its primary topic. Counting every listed topic
    would let one paper vote five times and would spread a small record across
    a dozen topics the person has never thought of as their field.
    """
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    subfields: dict[str, str] = {}
    venues: dict[str, Counter[str]] = {}

    for work in works:
        if not work.topic_id:
            continue
        counts[work.topic_id] += 1
        names.setdefault(work.topic_id, work.topic_name)
        subfields.setdefault(work.topic_id, work.topic_subfield)
        if work.source_name:
            venues.setdefault(work.topic_id, Counter())[work.source_name] += 1

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    kept = [tid for tid, n in ordered if n >= MIN_TOPIC_PAPERS][:limit]
    if len(kept) < WANTED_TOPICS:
        kept = [tid for tid, n in ordered if n >= RELAXED_TOPIC_PAPERS][:limit]
    if not kept:
        kept = [tid for tid, _ in ordered][:limit]

    return tuple(
        TopicProposal(
            id=tid,
            name=names.get(tid, ""),
            papers=counts[tid],
            subfield=subfields.get(tid, ""),
            venues=tuple(
                venue
                for venue, _ in venues.get(tid, Counter()).most_common(
                    TOP_VENUES_PER_TOPIC
                )
            ),
        )
        for tid in kept
    )


def subfield_label(proposals: Sequence[TopicProposal]) -> str:
    """Plain words for the subfield, for slide headings and report prose."""
    weighted: Counter[str] = Counter()
    for proposal in proposals:
        if proposal.subfield:
            weighted[proposal.subfield] += proposal.papers
    if weighted:
        return weighted.most_common(1)[0][0].lower()
    if proposals and proposals[0].name:
        return proposals[0].name.lower()
    return "unnamed subfield"


# ------------------------------------------------------------ pure: split IDs


def is_split_profile(primary: Mapping, candidate: Mapping, ror: str) -> bool:
    """Is this candidate a fragment of the same person's record?

    Conservative on purpose. Merging two people invents a career nobody had,
    and the cost of missing a fragment is a handful of papers.
    """
    primary_id = _short_author_id(primary.get("id"))
    candidate_id = _short_author_id(candidate.get("id"))
    if not candidate_id or candidate_id == primary_id:
        return False

    # A profile carrying its own, different ORCID is somebody else.
    primary_orcid = _short_orcid(primary.get("orcid"))
    candidate_orcid = _short_orcid(candidate.get("orcid"))
    if candidate_orcid and candidate_orcid != primary_orcid:
        return False

    if not _names_match(primary, candidate):
        return False

    primary_works = int(primary.get("works_count") or 0)
    candidate_works = int(candidate.get("works_count") or 0)
    if candidate_works <= 0 or candidate_works > SPLIT_MAX_WORKS:
        return False
    if primary_works and candidate_works > SPLIT_MAX_SHARE * primary_works:
        return False

    if not _affiliated_with(candidate, ror):
        return False

    candidate_topics = _topic_ids(candidate)
    if not candidate_topics:
        return False
    return bool(_topic_ids(primary) & candidate_topics)


def _names_match(primary: Mapping, candidate: Mapping) -> bool:
    primary_keys = {_name_key(n) for n in _all_names(primary)} - {None}
    candidate_keys = {_name_key(n) for n in _all_names(candidate)} - {None}
    return any(
        _keys_agree(left, right) for left in primary_keys for right in candidate_keys
    )


def _keys_agree(left: tuple[str, str], right: tuple[str, str]) -> bool:
    """Same surname, and first names that can be the same person's.

    Two spelled-out first names have to match outright. Matching on the initial
    alone would merge `Tyler Sparks` into `Taylor Sparks`, and OpenAlex has
    plenty of both at one university. An initial only matches a full name when
    one side is genuinely abbreviated, which is the `J. Doe` case that split
    profiles actually take.
    """
    if left[0] != right[0]:
        return False
    first, other = left[1], right[1]
    if len(first) == 1 or len(other) == 1:
        return first[0] == other[0]
    return first == other


def _all_names(record: Mapping) -> list[str]:
    names = [str(record.get("display_name") or "")]
    alternatives = record.get("display_name_alternatives") or []
    if isinstance(alternatives, list):
        names.extend(str(a) for a in alternatives)
    return [n for n in names if n.strip()]


def _name_key(name: str) -> tuple[str, str] | None:
    """Surname and first name, normalized. `Jane Q. Doe` keys to (doe, jane).

    OpenAlex writes names both ways round, so `Sparks, Taylor D.` has to key the
    same as `Taylor D. Sparks`. A trailing comma in the raw string is the tell.
    """
    raw = _strip_accents(name).lower()
    inverted = "," in raw
    cleaned = _PUNCTUATION.sub(" ", raw)
    parts = [p for p in _WHITESPACE.split(cleaned) if p and p not in _NAME_SUFFIXES]
    if len(parts) < 2:
        return None
    if inverted:
        return parts[0], parts[1]
    return parts[-1], parts[0]


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _affiliated_with(record: Mapping, ror: str) -> bool:
    short = ror.rstrip("/").rsplit("/", 1)[-1].lower()
    for affiliation in record.get("affiliations") or []:
        institution = (affiliation or {}).get("institution") or {}
        value = str(institution.get("ror") or "")
        if value.rstrip("/").rsplit("/", 1)[-1].lower() == short:
            return True
    return False


def _topic_ids(record: Mapping) -> set[str]:
    out: set[str] = set()
    for topic in record.get("topics") or []:
        topic_id = _short_topic_id((topic or {}).get("id"))
        if topic_id:
            out.add(topic_id)
    return out


# -------------------------------------------------------------- pure: parsing


def parse_work(raw: Mapping) -> Work:
    """Trim an OpenAlex work down to the fields this tool reads."""
    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    topic = raw.get("primary_topic") or {}
    subfield = (topic.get("subfield") or {}).get("display_name") or ""

    bylines = []
    for authorship in raw.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        author_id = _short_author_id(author.get("id"))
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
        doi=_normalize_doi(raw.get("doi")),
        title=str(raw.get("title") or ""),
        type=str(raw.get("type") or ""),
        source_id=str(source.get("id") or ""),
        source_name=str(source.get("display_name") or ""),
        source_type=str(source.get("type") or ""),
        topic_id=_short_topic_id(topic.get("id")),
        topic_name=str(topic.get("display_name") or ""),
        topic_subfield=str(subfield),
        cited_by_count=int(raw.get("cited_by_count") or 0),
        bylines=tuple(bylines),
    )


def _normalize_title(title: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", (title or "").lower())).strip()


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text.rsplit("doi.org/", 1)[-1]


def _short_author_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"A\d+", text) else ""


def _short_topic_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"T\d+", text) else ""


def _short_orcid(value: object) -> str:
    text = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return text if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", text) else ""


def _ror_short(value: object) -> str:
    text = str(value or "").strip().lower().rstrip("/").rsplit("/", 1)[-1]
    return text if ROR_RE.match(text) else ""


# -------------------------------------------------------------------- network


def resolve_institution(
    client: OpenAlexClient, text: str
) -> tuple[Institution, tuple[Institution, ...]]:
    """Turn a name or a ROR into one institution, plus the runners-up.

    The runners-up get printed so someone at `University of Washington` can see
    immediately that they were matched to `Washington University`.
    """
    text = (text or "").strip()
    if not text:
        raise InitError("give an institution, either its name or its ROR")

    short = _ror_short(text)
    if short:
        try:
            body = client.get(
                f"/institutions/ror:{short}", {"select": INSTITUTIONS_SELECT}
            )
        except OpenAlexHTTPError as exc:
            if exc.status_code == 404:
                raise InitError(
                    f"OpenAlex has no institution with ROR {short}"
                ) from exc
            raise
        return _institution(body), ()

    page = client.get(
        "/institutions",
        {"search": text, "per-page": 10, "select": INSTITUTIONS_SELECT},
    )
    results = [r for r in (page.get("results") or []) if _ror_short(r.get("ror"))]
    if not results:
        raise InitError(
            f"OpenAlex found no institution matching {text!r}. Try the full "
            "official name, or paste the ROR from https://ror.org."
        )
    ranked = sorted(
        results,
        key=lambda r: (
            str(r.get("type") or "") != "education",
            -int(r.get("works_count") or 0),
        ),
    )
    return _institution(ranked[0]), tuple(_institution(r) for r in ranked[1:4])


def _institution(raw: Mapping) -> Institution:
    short = _ror_short(raw.get("ror")) or _ror_short(raw.get("id"))
    if not short:
        raise InitError("OpenAlex returned an institution with no usable ROR")
    return Institution(
        ror=f"https://ror.org/{short}",
        name=str(raw.get("display_name") or ""),
        country_code=str(raw.get("country_code") or ""),
        type=str(raw.get("type") or ""),
        works_count=int(raw.get("works_count") or 0),
    )


def resolve_author(client: OpenAlexClient, orcid: str) -> dict:
    """Fetch the author record behind an ORCID."""
    short = _short_orcid(orcid)
    if not short:
        raise InitError(
            f"{orcid!r} is not a valid ORCID. It looks like 0000-0002-1825-0097, "
            "and yours is at the top of your ORCID profile page."
        )
    try:
        body = client.get(f"/authors/orcid:{short}", {"select": AUTHORS_SELECT})
    except OpenAlexHTTPError as exc:
        if exc.status_code == 404:
            raise InitError(
                f"OpenAlex has no author record for ORCID {short}. That usually "
                "means the ORCID is not yet linked to any indexed papers. Check "
                "the ORCID, or add your works at orcid.org and try again in a day."
            ) from exc
        raise
    if not _short_author_id(body.get("id")):
        raise InitError(f"OpenAlex returned no author ID for ORCID {short}")
    return dict(body)


def find_split_profiles(
    client: OpenAlexClient, primary: Mapping, ror: str
) -> list[dict]:
    """Stray profiles at the same institution that belong to the same person."""
    name = str(primary.get("display_name") or "").strip()
    short = _ror_short(ror)
    if not name or not short:
        return []
    page = client.get(
        "/authors",
        {
            "filter": f"affiliations.institution.ror:{short}",
            "search": name,
            "per-page": 25,
            "select": AUTHORS_SELECT,
        },
    )
    return [
        dict(candidate)
        for candidate in (page.get("results") or [])
        if is_split_profile(primary, candidate, ror)
    ]


def fetch_works(
    client: OpenAlexClient,
    author_ids: Sequence[str],
    first_year: int,
    last_year: int,
) -> list[Work]:
    """Every work by any of these author IDs, unioned by DOI."""
    unioned: dict[str, Work] = {}
    for author_id in author_ids:
        filters = (
            f"authorships.author.id:{author_id},"
            f"publication_year:{first_year}-{last_year}"
        )
        for raw in client.paginate(
            "/works", {"filter": filters, "select": WORKS_SELECT}
        ):
            work = parse_work(raw)
            if not work.year:
                continue
            unioned.setdefault(work.key, work)
    return sorted(unioned.values(), key=lambda w: (-w.year, w.title, w.id))


# -------------------------------------------------------------- orchestration


def initialize(
    client: OpenAlexClient,
    *,
    orcid: str,
    institution: str,
    start_year: int,
    today: _dt.date | None = None,
) -> InitResult:
    """Run the whole `init` stage and return what it found."""
    today = today or _dt.date.today()
    this_year = today.year
    if start_year > this_year + 1:
        raise InitError(
            f"the appointment year {start_year} is in the future; give the first "
            "calendar year you were on the tenure line"
        )

    place, alternatives = resolve_institution(client, institution)
    author = resolve_author(client, orcid)
    primary_id = _short_author_id(author.get("id"))

    splits = find_split_profiles(client, author, place.ror)
    alt_ids = tuple(sorted(_short_author_id(s.get("id")) for s in splits))
    author_ids = (primary_id, *alt_ids)

    first_year = max(1900, start_year - LOOKBACK_YEARS)
    works = fetch_works(client, author_ids, first_year, this_year)
    defaults = CohortSpec()
    window, basis = select_window_works(
        works, author_ids, place.ror, start_year, defaults.article_types
    )
    topics = propose_topics(window)
    if not topics:
        raise InitError(
            "none of the papers OpenAlex has for you carry a topic yet, so there "
            "is nothing to name a subfield from. This usually means the ORCID is "
            "linked to very few indexed papers."
        )

    topics, combined_reach = measure_reach(client, topics, defaults.countries)

    result = InitResult(
        subject_name=str(author.get("display_name") or ""),
        author_id=primary_id,
        institution=place,
        start_year=start_year,
        topics=topics,
        label=subfield_label(topics),
        orcid=_short_orcid(orcid),
        alt_author_ids=alt_ids,
        institution_alternatives=alternatives,
        works_seen=len(works),
        window_works=len(window),
        fetched_from=first_year,
        combined_reach=combined_reach,
        basis=basis,
        current_career_year=this_year - start_year + 1,
        notes=tuple(
            _notes(place, alternatives, splits, window, basis, topics, start_year)
        ),
    )
    return InitResult(**{**result.__dict__, "config": draft_config(result)})


def _notes(
    place: Institution,
    alternatives: Sequence[Institution],
    splits: Sequence[Mapping],
    window: Sequence[Work],
    basis: str,
    topics: Sequence[TopicProposal],
    start_year: int,
) -> Iterable[str]:
    """Everything the person should read before accepting the proposal."""
    if place.type and place.type != "education":
        yield (
            f"OpenAlex classes {place.name} as {place.type}, not education. If that "
            "is wrong, or it matched the wrong place, rerun with the ROR."
        )
    if alternatives:
        names = ", ".join(a.name for a in alternatives if a.name)
        if names:
            yield f"Other institutions matching that name, not used: {names}."
    if splits:
        yield (
            f"{len(splits)} extra OpenAlex profile(s) at {place.name} look like the "
            "same person and were merged in. Their papers are counted once."
        )
    if basis == "since_start":
        yield (
            f"Fewer than {MIN_ANCHORED_WORKS} papers since {start_year} carry the "
            f"{place.name} byline, so the topics come from every paper you have "
            "published since then, wherever the byline points."
        )
    elif basis == "all_years":
        yield (
            f"No journal articles since {start_year} were found, so the topics come "
            "from your whole publication record, including the years before the "
            "appointment."
        )
    if len(topics) < WANTED_TOPICS:
        yield (
            f"Only {len(topics)} topic(s) carry enough of your papers to propose. A "
            "subfield this narrow makes for a small cohort, so consider adding a "
            "topic by hand before you run."
        )
    if len(window) < MIN_ANCHORED_WORKS:
        yield (
            f"The proposal rests on {len(window)} paper(s), which is thin. Read the "
            "topic list closely."
        )
    reaches = [t for t in topics if t.reach is not None]
    if reaches:
        widest = max(reaches, key=lambda t: t.reach or 0)
        total = sum(t.reach or 0 for t in reaches)
        if total and (widest.reach or 0) > LOPSIDED_TOPIC_SHARE * total:
            yield (
                f"{widest.id} ({widest.name}) alone brings in "
                f"{widest.reach:,} of those people while carrying "
                f"{widest.papers} of your papers. A topic that wide usually means "
                "a neighboring community, and dropping it is the cheapest way to "
                "make the run shorter and the cohort closer to your own."
            )


def measure_reach(
    client: OpenAlexClient,
    proposals: Sequence[TopicProposal],
    countries: Sequence[str],
) -> tuple[tuple[TopicProposal, ...], int | None]:
    """Ask how many people each proposed topic would put in the cohort.

    One request per topic, plus one for the set. That is a handful of requests
    against a stage that already made a dozen, and it is the only number at
    `init` time that predicts what the long stage will cost.

    A failure here loses the annotation, not the proposal: the topics are still
    correct without it, and refusing to finish `init` over a progress nicety
    would be the wrong trade.
    """
    annotated: list[TopicProposal] = []
    try:
        for proposal in proposals:
            reach = estimate_pool_size(client, [proposal.id], countries)
            annotated.append(replace(proposal, reach=reach))
        combined = estimate_pool_size(
            client, [p.id for p in proposals], countries
        )
    except OpenAlexError:
        return tuple(proposals), None
    return tuple(annotated), combined


def draft_config(result: InitResult) -> dict:
    """The `benchmark.yaml` mapping, in the order `benchmark.example.yaml` uses."""
    cohort = CohortSpec()
    output = OutputSpec()
    return {
        "subject": {
            "name": result.subject_name,
            "orcid": result.orcid,
            "openalex_author_ids": [result.author_id, *result.alt_author_ids],
            "institution_ror": result.institution.ror,
            "institution_name": result.institution.name,
            "start_year": result.start_year,
            "clock_notes": "",
        },
        "subfield": {
            "label": result.label,
            "topics": [{"id": t.id, "name": t.name} for t in result.topics],
            "excluded_topics": [],
        },
        "cohort": {
            "start_window": list(cohort.start_window),
            "horizon_years": cohort.horizon_years,
            "countries": list(cohort.countries),
            "institution_types": list(cohort.institution_types),
            "core_topic_share_min": cohort.core_topic_share_min,
            "min_led_papers": cohort.min_led_papers,
            "min_cell_size": cohort.min_cell_size,
            "bootstrap_iterations": cohort.bootstrap_iterations,
            "article_types": list(cohort.article_types),
        },
        "output": {
            "dir": str(output.dir),
            "slides": output.slides,
            "chaperone": output.chaperone,
        },
    }


_BASIS_WORDING = {
    "anchored": "journal articles carrying the {place} byline since {year}",
    "since_start": "journal articles published since {year}",
    "all_years": "every journal article on record",
}


def format_result(result: InitResult) -> str:
    """The printout `init` leaves on screen for the person to read."""
    place = result.institution
    basis = _BASIS_WORDING[result.basis].format(
        place=place.name, year=result.start_year
    )
    lines = [
        f"Subject: {result.subject_name} ({result.author_id})",
        f"Institution: {place.name} ({place.ror})",
        f"Appointment began {result.start_year}, so you are in career year "
        f"{result.current_career_year}.",
    ]
    if result.alt_author_ids:
        lines.append(f"Merged profiles: {', '.join(result.alt_author_ids)}")
    lines.append("")
    lines.append(
        f"Read {result.window_works} paper(s) of the {result.works_seen} OpenAlex "
        f"lists for you from {result.fetched_from} on: {basis}."
    )
    lines.append(f"Subfield: {result.label}")
    lines.append("")
    lines.append("Proposed topics, the ones carrying most of your papers first:")
    for i, topic in enumerate(result.topics, start=1):
        share = topic.share_of(result.window_works)
        lines.append(
            f"  {i}. {topic.id}  {topic.name} "
            f"({topic.papers} of your papers, {share:.0%})"
        )
        if topic.venues:
            lines.append(f"       your venues here: {', '.join(topic.venues)}")
        if topic.reach is not None:
            lines.append(f"       people this topic brings in: {topic.reach:,}")
    if result.combined_reach is not None:
        lines.append("")
        lines.append(
            f"All {len(result.topics)} together put {result.combined_reach:,} people "
            "in front of the filters."
        )
    if result.notes:
        lines.append("")
        lines.append("Worth reading before you run:")
        lines.extend(f"  - {note}" for note in result.notes)
    return "\n".join(lines)
