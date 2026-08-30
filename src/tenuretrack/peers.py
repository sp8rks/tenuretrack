"""Restrict the cohort to institutions of standing similar to the subject's.

A benchmark against every US university answers "what do people in my subfield
publish", which is the question most people mean. Some want a narrower one:
"what do people at schools like mine publish". This module answers the second
without pretending to information it does not have.

There is no prestige ranking in OpenAlex, and the ones people mean (US News,
Carnegie tiers) are not open data this tool can redistribute. So a peer here is
defined by what the data actually supports: an institution whose presence in
this subfield is closest to the subject's own. Institutions are ordered by how
many on-topic candidates they carry, the subject's institution is found in that
order, and the peer group is the window of institutions sitting either side of
it.

That is a claim about subfield output, not about prestige, and the report says
so. A school that is famous for something other than this subfield sits low in
this order, correctly for this purpose and wrongly for most others.

The cost of narrowing is people. A cohort of 1091 spread over 622 institutions
averages under two people per school, so a peer group of 15 leaves a cohort too
thin to carry quartiles. `enough_people` is what stands between a user and a
confident-looking median computed over nine people.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from tenuretrack.pool import Candidate

__all__ = [
    "InstitutionRank",
    "PeerGroup",
    "enough_people",
    "institution_ranking",
    "peer_group",
]

MIN_PEER_COHORT = 100
"""Below this many people, a peer-restricted cohort does not carry quartiles.

Not a hard stop, because it is the user's cohort and the tool's job is to say
what the numbers can bear, not to refuse. `enough_people` returns the warning
and the caller decides. The figure is a floor for a p25 and p75 that survive
resampling, not a rule from anywhere.
"""


@dataclass(frozen=True)
class InstitutionRank:
    """One institution's place in the subfield, by on-topic people."""

    ror: str
    name: str
    people: int


@dataclass(frozen=True)
class PeerGroup:
    """The institutions kept, and where the subject sat among them."""

    rors: frozenset[str]
    names: tuple[str, ...]
    subject_rank: int | None
    """The subject's 1-based place in the full ordering, or None when their
    institution carries no on-topic candidates at all."""

    total_institutions: int

    def __contains__(self, ror: str) -> bool:
        return _short(ror) in self.rors


def _short(ror: str) -> str:
    """ROR as its bare id, so a full URL and a bare id compare equal."""
    return str(ror or "").rstrip("/").rsplit("/", 1)[-1].lower()


def institution_ranking(
    candidates: Iterable[Candidate], institution_types: Sequence[str] = ("education",)
) -> tuple[InstitutionRank, ...]:
    """Order institutions by how many of these candidates they carry.

    Each person counts once, for the qualifying institution appearing earliest
    in their affiliation list, which is the one OpenAlex treats as primary.
    Counting every affiliation would let one person with a national-lab joint
    appointment vote several times.
    """
    wanted = {t.lower() for t in institution_types}
    people: Counter[str] = Counter()
    names: dict[str, str] = {}

    for person in candidates:
        for affiliation in person.affiliations:
            if affiliation.type.lower() not in wanted:
                continue
            ror = _short(affiliation.ror)
            if not ror:
                continue
            people[ror] += 1
            names.setdefault(ror, affiliation.name)
            break

    ordered = sorted(people.items(), key=lambda kv: (-kv[1], names.get(kv[0], "")))
    return tuple(
        InstitutionRank(ror=ror, name=names.get(ror, ""), people=count)
        for ror, count in ordered
    )


def peer_group(
    ranking: Sequence[InstitutionRank], subject_ror: str, size: int
) -> PeerGroup:
    """The `size` institutions nearest the subject's own in subfield output.

    The window is centred on the subject wherever it can be. Near either end of
    the ordering it slides rather than shrinks, so a subject at the very top
    gets `size` institutions below them rather than half a peer group.
    """
    if size <= 0:
        raise ValueError("peer group size must be positive")

    subject = _short(subject_ror)
    index = next((i for i, r in enumerate(ranking) if r.ror == subject), None)

    if not ranking:
        return PeerGroup(frozenset({subject}), (), None, 0)

    if index is None:
        # The subject's institution carries no on-topic candidates of its own,
        # so there is no place in the ordering to centre on. Take the top of
        # the ordering and say the rank is unknown rather than invent one.
        window = list(ranking[:size])
        rors = {r.ror for r in window} | {subject}
        return PeerGroup(frozenset(rors), tuple(r.name for r in window), None, len(ranking))

    half = size // 2
    start = max(0, index - half)
    start = min(start, max(0, len(ranking) - size))
    window = list(ranking[start : start + size])
    rors = {r.ror for r in window} | {subject}
    return PeerGroup(
        frozenset(rors),
        tuple(r.name for r in window),
        index + 1,
        len(ranking),
    )


def enough_people(cohort_size: int, floor: int = MIN_PEER_COHORT) -> str | None:
    """The warning to print when a peer group has cut the cohort too thin.

    Returns None when the cohort is large enough, so the caller can treat this
    as "say something or say nothing".
    """
    if cohort_size >= floor:
        return None
    return (
        f"The peer group leaves {cohort_size} people. Quartiles over a group "
        f"this small move a lot when one person joins or leaves, and the p25 "
        f"and p75 in particular are not worth much below about {floor}. "
        "Widen peer_group_size, or drop it and compare against the whole "
        "subfield."
    )
