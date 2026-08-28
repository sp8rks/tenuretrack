"""Subject resolution and topic proposal (`tenuretrack init`, TASKS.md task 2).

Every fixture here is synthetic. `Jane Doe` at `University of X` is nobody, and
the OpenAlex IDs are made up. No test touches the network: the one end-to-end
test drives a mock transport.
"""

from __future__ import annotations

import datetime as _dt
import re

import httpx
import pytest

from tenuretrack.config import MAX_TOPICS, build_config
from tenuretrack.guardrail import PRESCRIPTIVE_TERMS
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.subject import (
    InitError,
    draft_config,
    fetch_works,
    format_result,
    has_byline_at,
    initialize,
    is_journal_article,
    is_split_profile,
    parse_work,
    propose_topics,
    resolve_author,
    resolve_institution,
    select_window_works,
    subfield_label,
)

ROR = "https://ror.org/03r0ha626"
SHORT_ROR = "03r0ha626"
ORCID = "0000-0002-1825-0097"
TODAY = _dt.date(2026, 8, 28)


# ------------------------------------------------------------------- builders


def work(
    ident="W1",
    year=2020,
    doi="10.1/a",
    title="A paper",
    kind="article",
    source=("S1", "Journal of X", "journal"),
    topic=("T10001", "Topic A", "Subfield A"),
    authors=((("A100", "last", True), (ROR,)),),
):
    """A raw OpenAlex work, trimmed to the fields `parse_work` reads."""
    source_id, source_name, source_type = source or (None, None, None)
    topic_id, topic_name, topic_subfield = topic or (None, None, None)
    return {
        "id": f"https://openalex.org/{ident}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": year,
        "type": kind,
        "cited_by_count": 3,
        "primary_location": (
            {
                "source": {
                    "id": f"https://openalex.org/{source_id}",
                    "display_name": source_name,
                    "type": source_type,
                }
            }
            if source
            else {}
        ),
        "primary_topic": (
            {
                "id": f"https://openalex.org/{topic_id}",
                "display_name": topic_name,
                "subfield": {"display_name": topic_subfield},
            }
            if topic
            else None
        ),
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{aid}"},
                "author_position": position,
                "is_corresponding": corresponding,
                "institutions": [{"ror": r} for r in rors],
            }
            for (aid, position, corresponding), rors in authors
        ],
    }


def author(
    ident="A100",
    name="Jane Doe",
    orcid=ORCID,
    works_count=40,
    rors=(ROR,),
    topics=("T10001", "T10002"),
    alternatives=(),
):
    return {
        "id": f"https://openalex.org/{ident}",
        "display_name": name,
        "display_name_alternatives": list(alternatives),
        "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        "works_count": works_count,
        "affiliations": [
            {"institution": {"ror": r, "display_name": "University of X"}} for r in rors
        ],
        "topics": [{"id": f"https://openalex.org/{t}"} for t in topics],
    }


def parsed(**kwargs):
    return parse_work(work(**kwargs))


# --------------------------------------------------------------------- parsing


def test_parse_work_trims_to_the_fields_we_read():
    parsed_work = parsed()
    assert parsed_work.id == "https://openalex.org/W1"
    assert parsed_work.doi == "10.1/a"
    assert parsed_work.year == 2020
    assert parsed_work.source_name == "Journal of X"
    assert parsed_work.topic_id == "T10001"
    assert parsed_work.topic_subfield == "Subfield A"
    assert parsed_work.bylines[0].author_id == "A100"
    assert parsed_work.bylines[0].position == "last"
    assert parsed_work.bylines[0].institution_rors == (ROR,)


def test_parse_work_survives_a_record_with_nothing_in_it():
    empty = parse_work({})
    assert empty.year == 0
    assert empty.topic_id == ""
    assert empty.bylines == ()


def test_work_key_is_the_doi_when_there_is_one():
    assert parsed(doi="10.1/A").key == "10.1/a"


def test_work_key_falls_back_to_title_and_year():
    key = parsed(doi=None, title="The Same  Paper!").key
    assert key == "the same paper|2020"
    assert parsed(doi=None, title="the same paper", ident="W9").key == key


# ------------------------------------------------------------------- filtering


def test_journal_articles_are_kept():
    assert is_journal_article(parsed(), ["article"])


def test_preprints_on_a_repository_are_dropped():
    preprint = parsed(source=("S9", "arXiv", "repository"))
    assert not is_journal_article(preprint, ["article"])


def test_non_article_types_are_dropped():
    assert not is_journal_article(parsed(kind="book-chapter"), ["article"])


def test_a_work_with_no_source_is_still_an_article():
    assert is_journal_article(parsed(source=None), ["article"])


def test_byline_matches_regardless_of_ror_url_form():
    assert has_byline_at(parsed(), ["A100"], SHORT_ROR)
    assert has_byline_at(parsed(), ["a100"], ROR)


def test_byline_does_not_match_a_coauthors_institution():
    shared = parsed(
        authors=(
            (("A100", "first", False), ("https://ror.org/00000000a",)),
            (("A200", "last", True), (ROR,)),
        )
    )
    assert not has_byline_at(shared, ["A100"], ROR)


# ---------------------------------------------------------------- window rules


def anchored_set(n, start_ident=0):
    return [
        parsed(ident=f"W{start_ident + i}", doi=f"10.1/w{start_ident + i}", year=2020)
        for i in range(n)
    ]


def test_window_anchors_on_the_institution_byline():
    elsewhere = parsed(
        ident="W99",
        doi="10.1/elsewhere",
        authors=((("A100", "last", True), ("https://ror.org/00000000a",)),),
    )
    works = [*anchored_set(5), elsewhere]
    window, basis = select_window_works(works, ["A100"], ROR, 2019, ["article"])
    assert basis == "anchored"
    assert elsewhere not in window
    assert len(window) == 5


def test_a_thin_record_widens_to_every_paper_since_the_start_and_says_so():
    works = [
        *anchored_set(2),
        parsed(
            ident="W99",
            doi="10.1/elsewhere",
            authors=((("A100", "last", True), ("https://ror.org/00000000a",)),),
        ),
    ]
    window, basis = select_window_works(works, ["A100"], ROR, 2019, ["article"])
    assert basis == "since_start"
    assert len(window) == 3


def test_nothing_since_the_start_widens_to_the_whole_record():
    works = [parsed(year=2015, doi="10.1/old")]
    window, basis = select_window_works(works, ["A100"], ROR, 2019, ["article"])
    assert basis == "all_years"
    assert len(window) == 1


def test_the_window_never_includes_papers_before_the_appointment():
    works = [*anchored_set(5), parsed(ident="W98", doi="10.1/old", year=2014)]
    window, _ = select_window_works(works, ["A100"], ROR, 2019, ["article"])
    assert all(w.year >= 2019 for w in window)


# ------------------------------------------------------------ topic proposal


def topic_spread(counts):
    """One work per paper, spread across topics by the given counts."""
    works = []
    for topic_id, n in counts.items():
        for i in range(n):
            works.append(
                parsed(
                    ident=f"W{topic_id}{i}",
                    doi=f"10.1/{topic_id}-{i}",
                    topic=(topic_id, f"Name {topic_id}", "Shared subfield"),
                    source=("S1", f"Journal of {topic_id}", "journal"),
                )
            )
    return works


def test_topics_rank_by_how_many_papers_sit_in_them():
    proposals = propose_topics(
        topic_spread({"T10001": 5, "T10002": 4, "T10003": 3, "T10004": 3})
    )
    assert [p.id for p in proposals] == ["T10001", "T10002", "T10003", "T10004"]
    assert proposals[0].papers == 5


def test_a_topic_carrying_one_paper_is_not_proposed():
    proposals = propose_topics(
        topic_spread({"T10001": 5, "T10002": 4, "T10003": 3, "T10004": 3, "T10005": 1})
    )
    assert "T10005" not in [p.id for p in proposals]


def test_the_count_relaxes_rather_than_proposing_almost_nothing():
    proposals = propose_topics(topic_spread({"T10001": 5, "T10002": 2, "T10003": 2}))
    assert [p.id for p in proposals] == ["T10001", "T10002", "T10003"]


def test_a_record_too_thin_for_any_rule_still_proposes_something():
    proposals = propose_topics(topic_spread({"T10001": 1}))
    assert [p.id for p in proposals] == ["T10001"]


def test_no_more_than_six_topics_are_proposed():
    proposals = propose_topics(topic_spread({f"T1000{i}": 9 - i for i in range(9)}))
    assert len(proposals) == MAX_TOPICS


def test_a_proposal_carries_the_venues_that_justify_it():
    proposals = propose_topics(topic_spread({"T10001": 3}))
    assert proposals[0].venues == ("Journal of T10001",)


def test_works_with_no_topic_are_ignored():
    assert propose_topics([parsed(topic=None)]) == ()


def test_the_label_comes_from_the_subfield_carrying_most_papers():
    works = [
        *topic_spread({"T10001": 4}),
        parsed(ident="Wz", doi="10.1/z", topic=("T10009", "Other", "Other Subfield")),
    ]
    assert subfield_label(propose_topics(works)) == "shared subfield"


def test_the_label_falls_back_to_the_top_topic_name():
    proposals = propose_topics([parsed(topic=("T10001", "Battery Materials", ""))])
    assert subfield_label(proposals) == "battery materials"


# ------------------------------------------------------------- split profiles


def test_a_small_fragment_at_the_same_place_is_the_same_person():
    fragment = author(ident="A101", name="J. Doe", orcid=None, works_count=3)
    assert is_split_profile(author(), fragment, ROR)


def test_a_fragment_is_matched_through_an_alternative_name():
    fragment = author(
        ident="A101",
        name="Jane Roe",
        orcid=None,
        works_count=3,
        alternatives=["Jane Doe"],
    )
    assert is_split_profile(author(), fragment, ROR)


def test_a_profile_with_its_own_different_orcid_is_somebody_else():
    other = author(
        ident="A101", name="J. Doe", orcid="0000-0001-0000-0001", works_count=3
    )
    assert not is_split_profile(author(), other, ROR)


def test_two_substantial_profiles_are_never_merged():
    twin = author(ident="A101", name="J. Doe", orcid=None, works_count=38)
    assert not is_split_profile(author(), twin, ROR)


def test_a_fragment_elsewhere_is_not_merged():
    elsewhere = author(
        ident="A101",
        name="J. Doe",
        orcid=None,
        works_count=3,
        rors=("https://ror.org/00000000a",),
    )
    assert not is_split_profile(author(), elsewhere, ROR)


def test_a_namesake_in_another_field_is_not_merged():
    namesake = author(
        ident="A101", name="J. Doe", orcid=None, works_count=3, topics=("T20001",)
    )
    assert not is_split_profile(author(), namesake, ROR)


def test_a_different_name_at_the_same_place_is_not_merged():
    colleague = author(ident="A101", name="Robert Poe", orcid=None, works_count=3)
    assert not is_split_profile(author(), colleague, ROR)


def test_a_profile_is_not_a_fragment_of_itself():
    assert not is_split_profile(author(), author(), ROR)


def test_accents_and_suffixes_do_not_block_a_match():
    fragment = author(ident="A101", name="Jane Doe Jr.", orcid=None, works_count=2)
    assert is_split_profile(author(name="Jané Doe"), fragment, ROR)


# ---------------------------------------------------------------- the network


class Router:
    """A mock OpenAlex that answers by path, and records what it was asked."""

    def __init__(self, routes):
        self.routes = routes
        self.paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(str(request.url))
        for prefix, payload in self.routes.items():
            if path.startswith(prefix):
                body = payload(request) if callable(payload) else payload
                if isinstance(body, int):
                    return httpx.Response(body, json={"error": "no"})
                return httpx.Response(200, json=body)
        raise AssertionError(f"no route for {path}")

    def client(self, tmp_path):
        return OpenAlexClient(
            mailto="tester@example.edu",
            cache_dir=tmp_path / ".cache",
            transport=httpx.MockTransport(self.handler),
            requests_per_second=0,
            sleep=lambda _s: None,
        )


def page(results, next_cursor=None):
    return {"results": results, "meta": {"next_cursor": next_cursor}}


def test_a_ror_resolves_without_a_search(tmp_path):
    router = Router(
        {
            "/institutions": {
                "ror": ROR,
                "display_name": "University of X",
                "country_code": "US",
                "type": "education",
            }
        }
    )
    place, others = resolve_institution(router.client(tmp_path), ROR)
    assert place.ror == ROR
    assert others == ()
    assert "ror:03r0ha626" in router.paths[0]


def test_a_name_search_prefers_a_university_and_keeps_the_runners_up(tmp_path):
    router = Router(
        {
            "/institutions": page(
                [
                    {
                        "ror": "https://ror.org/00000000b",
                        "display_name": "X Hospital",
                        "type": "healthcare",
                        "works_count": 90000,
                    },
                    {
                        "ror": ROR,
                        "display_name": "University of X",
                        "type": "education",
                        "works_count": 50000,
                    },
                ]
            )
        }
    )
    place, others = resolve_institution(router.client(tmp_path), "University of X")
    assert place.name == "University of X"
    assert [o.name for o in others] == ["X Hospital"]


def test_an_unmatched_institution_says_what_to_do(tmp_path):
    router = Router({"/institutions": page([])})
    with pytest.raises(InitError, match="ror.org"):
        resolve_institution(router.client(tmp_path), "Nowhere Polytechnic")


def test_a_malformed_orcid_is_refused_before_any_request(tmp_path):
    router = Router({})
    with pytest.raises(InitError, match="not a valid ORCID"):
        resolve_author(router.client(tmp_path), "not-an-orcid")


def test_an_unknown_orcid_explains_itself(tmp_path):
    router = Router({"/authors": lambda _r: 404})
    with pytest.raises(InitError, match="not yet linked"):
        resolve_author(router.client(tmp_path), ORCID)


def test_works_from_two_profiles_are_unioned_by_doi(tmp_path):
    shared = work(ident="W1", doi="10.1/shared")
    only_alt = work(ident="W2", doi="10.1/alt")

    def works(request):
        if "A101" in str(request.url):
            return page([shared, only_alt])
        return page([shared])

    router = Router({"/works": works})
    found = fetch_works(router.client(tmp_path), ["A100", "A101"], 2011, 2026)
    assert sorted(w.doi for w in found) == ["10.1/alt", "10.1/shared"]


# ----------------------------------------------------------------- end to end


def full_router(window_works=None):
    primary = author()
    fragment = author(ident="A101", name="J. Doe", orcid=None, works_count=2)
    works = window_works if window_works is not None else default_works()

    def works_route(request):
        if "A101" in str(request.url):
            return page([])
        return page(works)

    def authors_route(request):
        if "orcid:" in str(request.url):
            return primary
        return page([primary, fragment])

    return Router(
        {
            "/institutions": {
                "ror": ROR,
                "display_name": "University of X",
                "country_code": "US",
                "type": "education",
            },
            "/authors": authors_route,
            "/works": works_route,
        }
    )


def default_works():
    """Nine window articles across three topics, plus noise that must be dropped."""
    out = []
    for topic_id, n in (("T10001", 4), ("T10002", 3), ("T10003", 2)):
        for i in range(n):
            out.append(
                work(
                    ident=f"W{topic_id}{i}",
                    doi=f"10.1/{topic_id}-{i}",
                    year=2021,
                    topic=(topic_id, f"Name {topic_id}", "Materials chemistry"),
                    source=("S1", f"Journal of {topic_id}", "journal"),
                )
            )
    out.append(work(ident="Wpre", doi="10.1/pre", source=("S9", "arXiv", "repository")))
    out.append(work(ident="Wold", doi="10.1/old", year=2014))
    return out


def test_initialize_reads_the_window_and_proposes_topics(tmp_path):
    router = full_router()
    result = initialize(
        router.client(tmp_path),
        orcid=ORCID,
        institution=ROR,
        start_year=2019,
        today=TODAY,
    )
    assert result.subject_name == "Jane Doe"
    assert result.author_id == "A100"
    assert result.alt_author_ids == ("A101",)
    assert result.institution.ror == ROR
    assert result.current_career_year == 8
    assert result.basis == "anchored"
    assert result.window_works == 9  # the preprint and the 2014 paper are out
    assert [t.id for t in result.topics] == ["T10001", "T10002", "T10003"]
    assert result.label == "materials chemistry"


def test_initialize_asks_openalex_for_the_years_it_needs(tmp_path):
    router = full_router()
    initialize(
        router.client(tmp_path),
        orcid=ORCID,
        institution=ROR,
        start_year=2019,
        today=TODAY,
    )
    works_calls = [p for p in router.paths if "/works" in p]
    assert any("publication_year%3A2011-2026" in p for p in works_calls)


def test_initialize_writes_a_config_that_validates(tmp_path):
    router = full_router()
    result = initialize(
        router.client(tmp_path),
        orcid=ORCID,
        institution=ROR,
        start_year=2019,
        today=TODAY,
    )
    config = build_config(dict(result.config))
    assert config.subject.orcid == ORCID
    assert config.subject.openalex_author_ids == ("A100", "A101")
    assert config.subject.institution_ror == ROR
    assert config.subject.start_year == 2019
    assert config.subfield.topic_ids == ("T10001", "T10002", "T10003")
    assert config.is_runnable


def test_initialize_refuses_an_appointment_in_the_future(tmp_path):
    router = full_router()
    with pytest.raises(InitError, match="in the future"):
        initialize(
            router.client(tmp_path),
            orcid=ORCID,
            institution=ROR,
            start_year=2030,
            today=TODAY,
        )


def test_initialize_refuses_a_record_with_no_topics_at_all(tmp_path):
    router = full_router([work(ident="W1", doi="10.1/a", topic=None)])
    with pytest.raises(InitError, match="nothing to name a subfield from"):
        initialize(
            router.client(tmp_path),
            orcid=ORCID,
            institution=ROR,
            start_year=2019,
            today=TODAY,
        )


def test_a_rerun_repeats_no_requests(tmp_path):
    router = full_router()
    cache = tmp_path / ".cache"
    kwargs = dict(orcid=ORCID, institution=ROR, start_year=2019, today=TODAY)

    first = OpenAlexClient(
        mailto="t@example.edu",
        cache_dir=cache,
        transport=httpx.MockTransport(router.handler),
        requests_per_second=0,
    )
    initialize(first, **kwargs)
    assert first.request_count > 0

    second = OpenAlexClient(
        mailto="t@example.edu",
        cache_dir=cache,
        transport=httpx.MockTransport(router.handler),
        requests_per_second=0,
    )
    initialize(second, **kwargs)
    assert second.request_count == 0
    assert second.cache_hits > 0


# ------------------------------------------------------------------ printout


def result_for(tmp_path, **overrides):
    router = full_router(overrides.pop("works", None))
    return initialize(
        router.client(tmp_path),
        orcid=ORCID,
        institution=ROR,
        start_year=overrides.pop("start_year", 2019),
        today=TODAY,
    )


def test_the_printout_shows_the_evidence_for_each_topic(tmp_path):
    text = format_result(result_for(tmp_path))
    assert "T10001" in text
    assert "4 of your papers" in text
    assert "Journal of T10001" in text


def test_the_printout_says_when_profiles_were_merged(tmp_path):
    text = format_result(result_for(tmp_path))
    assert "A101" in text
    assert "merged in" in text


def test_the_printout_says_when_it_had_to_widen(tmp_path):
    thin = [work(ident="W1", doi="10.1/a", year=2021, topic=("T10001", "A", "Chem"))]
    text = format_result(result_for(tmp_path, works=thin))
    assert "wherever the byline points" in text


def test_the_printout_stays_descriptive(tmp_path):
    text = format_result(result_for(tmp_path)).lower()
    for term in PRESCRIPTIVE_TERMS:
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in term.split()) + r"\b"
        assert not re.search(pattern, text), f"{term!r} turns a description into an instruction"


def test_no_em_dashes_anywhere_in_the_printout(tmp_path):
    assert "—" not in format_result(result_for(tmp_path))


def test_draft_config_matches_the_documented_schema(tmp_path):
    config = draft_config(result_for(tmp_path))
    assert set(config) == {"subject", "subfield", "cohort", "output"}
    build_config(config)  # raises if a key or a value is wrong
