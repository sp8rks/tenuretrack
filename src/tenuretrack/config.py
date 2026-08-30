"""Load and validate a `benchmark.yaml` subject spec.

The schema is documented by `benchmark.example.yaml`. Validation collects every
problem it can find and raises a single `ConfigError` listing all of them, so a
user editing the file by hand fixes everything in one pass.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ConfigError",
    "Config",
    "Subject",
    "Subfield",
    "CohortSpec",
    "OutputSpec",
    "Topic",
    "load_config",
]

PLACEHOLDER = "FILL_ME"
"""Value written by `init` for fields the user must confirm before `run`."""

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
ROR_RE = re.compile(r"^0[0-9a-hjkmnp-tv-z]{8}$")
TOPIC_ID_RE = re.compile(r"^T\d{4,}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
AUTHOR_ID_RE = re.compile(r"^A\d+$")

MIN_START_YEAR = 1950
MIN_CELL_SIZE_FLOOR = 5
"""Cells smaller than this can re-identify a cohort member. See the
aggregates-only rule in CLAUDE.md."""

MAX_TOPICS = 6
"""The ceiling for a hand-edited config.

`init` proposes at most `MAX_PROPOSED_TOPICS`, which is lower: a list of three
is one a person can actually read and judge. This stays at six because a config
written before that cap, including the committed worked example, is still a
valid description of a cohort that was really built.
"""

MAX_PROPOSED_TOPICS = 3

_SECTIONS = ("subject", "subfield", "cohort", "output")
_SUBJECT_KEYS = {
    "name",
    "orcid",
    "openalex_author_ids",
    "institution_ror",
    "institution_name",
    "start_year",
    "clock_extension_years",
    "clock_notes",
}
_SUBFIELD_KEYS = {"label", "topics", "excluded_topics"}
_COHORT_KEYS = {
    "start_window",
    "horizon_years",
    "countries",
    "institution_types",
    "core_topic_share_min",
    "excluded_venues",
    "min_led_papers",
    "min_cell_size",
    "peer_group_size",
    "bootstrap_iterations",
    "article_types",
}
_OUTPUT_KEYS = {"dir", "slides", "chaperone"}
_TOPIC_KEYS = {"id", "name"}


class ConfigError(ValueError):
    """Raised when `benchmark.yaml` is missing, malformed, or inconsistent."""

    def __init__(self, problems: list[str], source: Path | None = None) -> None:
        self.problems = list(problems)
        self.source = source
        where = f" in {source}" if source is not None else ""
        joined = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"invalid benchmark config{where}:\n{joined}")


@dataclass(frozen=True)
class Topic:
    """An OpenAlex topic (`T10123`) with the display name shown to the user."""

    id: str
    name: str = ""


@dataclass(frozen=True)
class Subject:
    """The one person being placed against the cohort."""

    name: str
    institution_ror: str
    institution_name: str
    start_year: int
    orcid: str | None = None
    openalex_author_ids: tuple[str, ...] = ()
    clock_extension_years: int = 0
    """Years the tenure clock was stopped, for parental or medical leave, or
    for a pandemic extension.

    An extension does not remove the work done during it. It grants extra
    calendar time to reach the same point on the clock, so somebody two years
    into an extended clock is compared against a cohort at year two while their
    papers are counted across all three calendar years they have had. Reading
    them at their calendar year instead would compare them against people who
    had uninterrupted time, which is what the extension exists to prevent.
    """
    clock_notes: str = ""

    def career_year(self, publication_year: int) -> int:
        """Calendar career year of a paper. Year 1 is the appointment year."""
        return publication_year - self.start_year + 1

    def current_career_year(self, today: _dt.date | None = None) -> int:
        """Calendar years elapsed since the appointment began, counting this one."""
        today = today or _dt.date.today()
        return self.career_year(today.year)

    def clock_year(self, today: _dt.date | None = None) -> int:
        """Position on the tenure clock, with any stopped years taken out."""
        return max(1, self.current_career_year(today) - self.clock_extension_years)


@dataclass(frozen=True)
class Subfield:
    """The topic set that defines the subfield."""

    label: str
    topics: tuple[Topic, ...] = ()
    excluded_topics: tuple[Topic, ...] = ()

    @property
    def topic_ids(self) -> tuple[str, ...]:
        return tuple(t.id for t in self.topics)


@dataclass(frozen=True)
class CohortSpec:
    """Cohort construction knobs. Defaults match `benchmark.example.yaml`."""

    start_window: tuple[int, int] = (2008, 2018)
    horizon_years: int = 6
    countries: tuple[str, ...] = ("US",)
    institution_types: tuple[str, ...] = ("education",)
    core_topic_share_min: float = 0.4
    min_led_papers: int = 3
    min_cell_size: int = 5
    peer_group_size: int = 0
    """Keep only people at the N institutions nearest the subject's in subfield
    output. 0, the default, keeps every institution.

    Off by default because the whole-subfield cohort is the question most
    people mean, and because narrowing costs people fast: a cohort averaging
    under two per institution does not survive being cut to fifteen schools.
    See `tenuretrack/peers.py`.
    """
    bootstrap_iterations: int = 2000
    article_types: tuple[str, ...] = ("article",)
    excluded_venues: tuple[str, ...] = ()
    """Venues to leave out, by OpenAlex source ID or exact display name.

    Empty by default, because dropping a venue is a judgement about a field and
    not a rule the tool can derive. It exists because some conference abstract
    series carry an ISSN and are typed as journals by OpenAlex, so nothing in
    the data distinguishes them: `Bulletin of the American Physical Society`
    supplied 932 of one cohort's 122,111 window papers. Applied identically to
    the subject and to every cohort member.
    """

    @property
    def horizons(self) -> tuple[int, ...]:
        """The through-year-N horizons the report covers, N = 1..horizon_years."""
        return tuple(range(1, self.horizon_years + 1))


@dataclass(frozen=True)
class OutputSpec:
    dir: Path = Path("results")
    slides: bool = True
    chaperone: bool = True


@dataclass(frozen=True)
class Config:
    subject: Subject
    subfield: Subfield
    cohort: CohortSpec
    output: OutputSpec
    source: Path | None = field(default=None, compare=False)

    @property
    def is_runnable(self) -> bool:
        return not self.unresolved()

    def unresolved(self) -> list[str]:
        """Fields that `init` (task 2) still has to fill in before `run`."""
        problems: list[str] = []
        if not self.subject.orcid and not self.subject.openalex_author_ids:
            problems.append(
                "subject.orcid or subject.openalex_author_ids must be set "
                "(run `tenuretrack init` to resolve them)"
            )
        if not self.subfield.topics:
            problems.append(
                "subfield.topics is empty (run `tenuretrack init` to propose topics, "
                "then edit the list before `run`)"
            )
        return problems

    def require_runnable(self) -> None:
        """Raise unless every field a full run needs has been filled in."""
        problems = self.unresolved()
        if problems:
            raise ConfigError(problems, self.source)


def load_config(path: str | Path) -> Config:
    """Read and validate a `benchmark.yaml`."""
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError([f"no such config file: {path}"]) from exc
    except OSError as exc:
        raise ConfigError([f"could not read config file: {exc}"]) from exc
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError([f"could not parse YAML: {exc}"], path) from exc
    return build_config(data, path)


def build_config(data: Any, source: Path | None = None) -> Config:
    """Validate an already-parsed mapping. Kept pure so tests need no files."""
    problems: list[str] = []
    if data is None:
        raise ConfigError(["config file is empty"], source)
    if not isinstance(data, dict):
        raise ConfigError(["top level of the config must be a mapping"], source)

    _check_unknown(data, set(_SECTIONS), "top level", problems)
    for section in _SECTIONS:
        value = data.get(section)
        if value is None:
            problems.append(f"missing required section: {section}")
        elif not isinstance(value, dict):
            problems.append(f"section {section} must be a mapping")
    if problems:
        raise ConfigError(problems, source)

    subject = _subject(data["subject"], problems)
    subfield = _subfield(data["subfield"], problems)
    cohort = _cohort(data["cohort"], problems)
    output = _output(data["output"], problems)

    if problems:
        raise ConfigError(problems, source)
    return Config(
        subject=subject,
        subfield=subfield,
        cohort=cohort,
        output=output,
        source=source,
    )


def _check_unknown(
    mapping: dict, allowed: set[str], where: str, problems: list[str]
) -> None:
    unknown = sorted(str(k) for k in set(mapping) - allowed)
    if unknown:
        problems.append(f"unknown key(s) at {where}: {', '.join(unknown)}")


def _placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper() == PLACEHOLDER


def _subject(raw: dict, problems: list[str]) -> Subject:
    _check_unknown(raw, _SUBJECT_KEYS, "subject", problems)

    name = _require_str(raw, "name", "subject", problems)

    orcid_raw = raw.get("orcid")
    orcid: str | None = None
    if orcid_raw is None or orcid_raw == "" or _placeholder(orcid_raw):
        orcid = None
    elif not isinstance(orcid_raw, str):
        problems.append("subject.orcid must be a string")
    else:
        candidate = orcid_raw.strip().upper().rstrip("/").rsplit("/", 1)[-1]
        if ORCID_RE.match(candidate):
            orcid = candidate
        else:
            problems.append(
                f"subject.orcid is not a valid ORCID: {orcid_raw!r} "
                "(expected 0000-0000-0000-0000)"
            )

    ids_raw = raw.get("openalex_author_ids") or []
    author_ids: list[str] = []
    if not isinstance(ids_raw, list):
        problems.append("subject.openalex_author_ids must be a list")
    else:
        for item in ids_raw:
            if not isinstance(item, str):
                problems.append("subject.openalex_author_ids entries must be strings")
                continue
            short = item.strip().rstrip("/").rsplit("/", 1)[-1].upper()
            if AUTHOR_ID_RE.match(short):
                author_ids.append(short)
            else:
                problems.append(
                    "subject.openalex_author_ids entry is not an OpenAlex author ID: "
                    f"{item!r}"
                )

    ror = _ror(raw.get("institution_ror"), problems)
    institution_name = _require_str(raw, "institution_name", "subject", problems)

    start_year = 0
    year_raw = raw.get("start_year")
    this_year = _dt.date.today().year
    if isinstance(year_raw, bool) or not isinstance(year_raw, int):
        problems.append("subject.start_year is required and must be an integer year")
    elif not MIN_START_YEAR <= year_raw <= this_year + 1:
        problems.append(
            f"subject.start_year {year_raw} is outside "
            f"{MIN_START_YEAR} to {this_year + 1}"
        )
    else:
        start_year = year_raw

    extension = 0
    ext_raw = raw.get("clock_extension_years", 0)
    if isinstance(ext_raw, bool) or not isinstance(ext_raw, int):
        problems.append("subject.clock_extension_years must be a whole number of years")
    elif not 0 <= ext_raw <= 10:
        problems.append(
            f"subject.clock_extension_years {ext_raw} is outside 0 to 10"
        )
    else:
        extension = ext_raw

    notes = raw.get("clock_notes") or ""
    if not isinstance(notes, str):
        problems.append("subject.clock_notes must be a string")
        notes = ""

    return Subject(
        name=name,
        institution_ror=ror,
        institution_name=institution_name,
        start_year=start_year,
        orcid=orcid,
        openalex_author_ids=tuple(author_ids),
        clock_extension_years=extension,
        clock_notes=notes,
    )


def _ror(value: Any, problems: list[str]) -> str:
    """Normalize a ROR to the full URL form the OpenAlex works filter expects."""
    if not isinstance(value, str) or not value.strip():
        problems.append("subject.institution_ror is required")
        return ""
    short = value.strip().lower().rstrip("/").rsplit("/", 1)[-1]
    if not ROR_RE.match(short):
        problems.append(
            f"subject.institution_ror is not a valid ROR: {value!r} "
            "(expected https://ror.org/03r0ha626)"
        )
        return ""
    return f"https://ror.org/{short}"


def _require_str(raw: dict, key: str, where: str, problems: list[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}.{key} is required and must be a non-empty string")
        return ""
    return value.strip()


def _subfield(raw: dict, problems: list[str]) -> Subfield:
    _check_unknown(raw, _SUBFIELD_KEYS, "subfield", problems)
    label = _require_str(raw, "label", "subfield", problems)
    topics = _topics(raw.get("topics"), "subfield.topics", problems)
    excluded = _topics(raw.get("excluded_topics"), "subfield.excluded_topics", problems)

    seen: set[str] = set()
    for topic in topics:
        if topic.id in seen:
            problems.append(f"subfield.topics lists {topic.id} more than once")
        seen.add(topic.id)
    for topic in excluded:
        if topic.id in seen:
            problems.append(
                f"subfield lists {topic.id} in both topics and excluded_topics"
            )
    if len(topics) > MAX_TOPICS:
        problems.append(
            f"subfield.topics has {len(topics)} topics; the working range is 1 to "
            f"{MAX_TOPICS} (a wider set pulls a different community into the cohort)"
        )
    return Subfield(label=label, topics=topics, excluded_topics=excluded)


def _topics(value: Any, where: str, problems: list[str]) -> tuple[Topic, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        problems.append(f"{where} must be a list")
        return ()
    out: list[Topic] = []
    for item in value:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict):
            problems.append(f"{where} entries must be mappings with an id")
            continue
        _check_unknown(item, _TOPIC_KEYS, where, problems)
        topic_id = item.get("id")
        if isinstance(topic_id, str) and TOPIC_ID_RE.match(topic_id.strip().upper()):
            name = item.get("name") or ""
            if not isinstance(name, str):
                problems.append(f"{where} entry name must be a string")
                name = ""
            out.append(Topic(id=topic_id.strip().upper(), name=name.strip()))
        else:
            problems.append(
                f"{where} entry has an invalid OpenAlex topic id: {topic_id!r} "
                "(expected T10123)"
            )
    return tuple(out)


def _cohort(raw: dict, problems: list[str]) -> CohortSpec:
    _check_unknown(raw, _COHORT_KEYS, "cohort", problems)
    defaults = CohortSpec()
    this_year = _dt.date.today().year

    window = raw.get("start_window", list(defaults.start_window))
    start_window = defaults.start_window
    if (
        not isinstance(window, (list, tuple))
        or len(window) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in window)
    ):
        problems.append(
            "cohort.start_window must be two integer years, e.g. [2008, 2018]"
        )
    elif window[0] > window[1]:
        problems.append(
            f"cohort.start_window is backwards: {window[0]} is after {window[1]}"
        )
    elif window[0] < MIN_START_YEAR or window[1] > this_year:
        problems.append(
            f"cohort.start_window {list(window)} is outside "
            f"{MIN_START_YEAR} to {this_year}"
        )
    else:
        start_window = (int(window[0]), int(window[1]))

    horizon = _int(
        raw, "horizon_years", defaults.horizon_years, 1, 20, "cohort", problems
    )
    countries = _str_list(raw, "countries", defaults.countries, "cohort", problems)
    for code in countries:
        if not COUNTRY_RE.match(code):
            problems.append(
                f"cohort.countries entry {code!r} is not a two-letter country code"
            )
    inst_types = _str_list(
        raw, "institution_types", defaults.institution_types, "cohort", problems
    )
    article_types = _str_list(
        raw, "article_types", defaults.article_types, "cohort", problems
    )
    excluded_venues: list[str] = []
    raw_excluded = raw.get("excluded_venues", [])
    if raw_excluded in (None, []):
        excluded_venues = []
    elif not isinstance(raw_excluded, list):
        problems.append("cohort.excluded_venues must be a list of venue names or IDs")
    else:
        for item in raw_excluded:
            if isinstance(item, str) and item.strip():
                excluded_venues.append(item.strip())
            else:
                problems.append(
                    "cohort.excluded_venues entries must be non-empty strings"
                )

    share = raw.get("core_topic_share_min", defaults.core_topic_share_min)
    core_share = defaults.core_topic_share_min
    if isinstance(share, bool) or not isinstance(share, (int, float)):
        problems.append("cohort.core_topic_share_min must be a number between 0 and 1")
    elif not 0.0 <= float(share) <= 1.0:
        problems.append(
            f"cohort.core_topic_share_min {share} is outside 0 to 1 "
            "(it is a share, not a percent)"
        )
    else:
        core_share = float(share)

    min_led = _int(
        raw, "min_led_papers", defaults.min_led_papers, 0, 100, "cohort", problems
    )
    min_cell = _int(
        raw,
        "min_cell_size",
        defaults.min_cell_size,
        MIN_CELL_SIZE_FLOOR,
        1000,
        "cohort",
        problems,
        extra_note=(
            f"cells smaller than {MIN_CELL_SIZE_FLOOR} people can re-identify "
            "a cohort member"
        ),
    )
    peer_size = _int(
        raw, "peer_group_size", defaults.peer_group_size, 0, 5000, "cohort", problems
    )
    iterations = _int(
        raw,
        "bootstrap_iterations",
        defaults.bootstrap_iterations,
        100,
        100_000,
        "cohort",
        problems,
    )

    return CohortSpec(
        start_window=start_window,
        horizon_years=horizon,
        countries=tuple(countries),
        institution_types=tuple(inst_types),
        core_topic_share_min=core_share,
        min_led_papers=min_led,
        min_cell_size=min_cell,
        peer_group_size=peer_size,
        bootstrap_iterations=iterations,
        article_types=tuple(article_types),
        excluded_venues=tuple(excluded_venues),
    )


def _int(
    raw: dict,
    key: str,
    default: int,
    low: int,
    high: int,
    where: str,
    problems: list[str],
    extra_note: str = "",
) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{where}.{key} must be an integer")
        return default
    if not low <= value <= high:
        note = f" ({extra_note})" if extra_note else ""
        problems.append(f"{where}.{key} {value} is outside {low} to {high}{note}")
        return default
    return value


def _str_list(
    raw: dict, key: str, default: tuple[str, ...], where: str, problems: list[str]
) -> list[str]:
    value = raw.get(key, list(default))
    if not isinstance(value, list) or not value:
        problems.append(f"{where}.{key} must be a non-empty list of strings")
        return list(default)
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            problems.append(f"{where}.{key} entries must be non-empty strings")
            continue
        out.append(item.strip().upper() if key == "countries" else item.strip())
    return out or list(default)


def _output(raw: dict, problems: list[str]) -> OutputSpec:
    _check_unknown(raw, _OUTPUT_KEYS, "output", problems)
    defaults = OutputSpec()
    directory = raw.get("dir", str(defaults.dir))
    if not isinstance(directory, str) or not directory.strip():
        problems.append("output.dir must be a non-empty path")
        directory = str(defaults.dir)
    flags: dict[str, bool] = {}
    for key, default in (
        ("slides", defaults.slides),
        ("chaperone", defaults.chaperone),
    ):
        value = raw.get(key, default)
        if not isinstance(value, bool):
            problems.append(f"output.{key} must be true or false")
            value = default
        flags[key] = value
    return OutputSpec(
        dir=Path(directory.strip()),
        slides=flags["slides"],
        chaperone=flags["chaperone"],
    )
