"""The candidate pool and the first funnel filters (TASKS.md task 3).

Every author here is invented. No test touches the network, and no fixture
carries a real name: the pool is the one place in this codebase where names are
allowed to exist at all, and they belong in `data/` on a maintainer's machine,
not in a repository.
"""

from __future__ import annotations

import csv
import gzip
import json

import httpx
import pytest

from tenuretrack.config import build_config
from tenuretrack.guardrail import GuardrailViolation
from tenuretrack.openalex import OpenAlexClient, OpenAlexError
from tenuretrack.pool import (
    MIN_WORKS,
    POOL_FILENAME,
    Candidate,
    Funnel,
    TopicShare,
    build_pool,
    core_topic_share,
    estimate_pool_size,
    harvest_pool,
    has_university_affiliation,
    in_countries,
    load_pool,
    parse_candidate,
    pool_filter,
    screen_pool,
)

TOPICS = ("T10001", "T10002")


# ------------------------------------------------------------------- builders


def raw_author(
    ident="A1000001",
    name="Alex Roe",
    works=40,
    topics=(("T10001", 20, 0.5), ("T99999", 20, 0.5)),
    affiliations=(("03r0ha626", "US", "education", (2018, 2019)),),
    orcid=None,
    h_index=12,
):
    return {
        "id": f"https://openalex.org/{ident}",
        "display_name": name,
        "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        "works_count": works,
        "cited_by_count": works * 10,
        "summary_stats": {"h_index": h_index},
        "topics": [
            {"id": f"https://openalex.org/{tid}", "count": count, "share": share}
            for tid, count, share in topics
        ],
        "affiliations": [
            {
                "institution": {
                    "ror": f"https://ror.org/{ror}",
                    "display_name": "Somewhere",
                    "country_code": country,
                    "type": kind,
                },
                "years": list(years),
            }
            for ror, country, kind, years in affiliations
        ],
    }


def candidate(**kwargs):
    return parse_candidate(raw_author(**kwargs))


def config_for(config_dict, **cohort):
    config_dict["subfield"]["topics"] = [{"id": t} for t in TOPICS]
    config_dict["cohort"].update(cohort)
    return build_config(config_dict)


# -------------------------------------------------------------------- parsing


def test_parse_candidate_keeps_what_the_funnel_reads():
    person = candidate(orcid="0000-0002-1825-0097")
    assert person.author_id == "A1000001"
    assert person.name == "Alex Roe"
    assert person.orcid == "0000-0002-1825-0097"
    assert person.h_index == 12
    assert person.topics[0] == TopicShare(id="T10001", count=20, share=0.5)
    assert person.affiliations[0].ror == "03r0ha626"
    assert person.affiliations[0].country_code == "US"
    assert person.affiliations[0].type == "education"
    assert person.affiliations[0].years == (2018, 2019)


def test_parse_candidate_survives_an_empty_record():
    empty = parse_candidate({})
    assert empty.author_id == ""
    assert empty.topics == ()
    assert empty.affiliations == ()


def test_a_candidate_round_trips_through_the_on_disk_shape():
    person = candidate(orcid="0000-0002-1825-0097")
    assert Candidate.from_row(json.loads(json.dumps(person.to_row()))) == person


# ------------------------------------------------------------- core topic share


def test_core_topic_share_uses_the_share_field_when_it_is_there():
    person = candidate(topics=(("T10001", 5, 0.3), ("T99999", 5, 0.7)))
    assert core_topic_share(person, TOPICS) == pytest.approx(0.3)


def test_core_topic_share_sums_across_the_configured_topics():
    person = candidate(topics=(("T10001", 5, 0.3), ("T10002", 5, 0.2), ("T9", 5, 0.5)))
    assert core_topic_share(person, TOPICS) == pytest.approx(0.5)


def test_core_topic_share_falls_back_to_counts_when_share_is_missing():
    person = candidate(topics=(("T10001", 30, None), ("T99999", 10, None)))
    assert core_topic_share(person, TOPICS) == pytest.approx(0.75)


def test_core_topic_share_normalizes_shares_that_do_not_sum_to_one():
    person = candidate(topics=(("T10001", 5, 0.2), ("T99999", 5, 0.2)))
    assert core_topic_share(person, TOPICS) == pytest.approx(0.5)


def test_someone_with_no_topics_scores_zero_rather_than_raising():
    assert core_topic_share(candidate(topics=()), TOPICS) == 0.0


def test_a_topic_id_is_matched_case_insensitively():
    person = candidate(topics=(("T10001", 10, 1.0),))
    assert core_topic_share(person, ["t10001"]) == pytest.approx(1.0)


# ------------------------------------------------------------------ university


def test_a_university_affiliation_passes():
    assert has_university_affiliation(candidate(), ["education"])


def test_an_industry_only_profile_is_dropped():
    person = candidate(affiliations=(("03r0ha626", "US", "company", ()),))
    assert not has_university_affiliation(person, ["education"])


def test_a_national_lab_plus_university_person_stays():
    person = candidate(
        affiliations=(
            ("00000000a", "US", "facility", ()),
            ("03r0ha626", "US", "education", ()),
        )
    )
    assert has_university_affiliation(person, ["education"])


def test_a_hospital_only_profile_is_dropped():
    person = candidate(affiliations=(("00000000a", "US", "healthcare", ()),))
    assert not has_university_affiliation(person, ["education"])


def test_country_matching_looks_across_every_affiliation():
    person = candidate(
        affiliations=(
            ("00000000a", "DE", "education", ()),
            ("03r0ha626", "US", "education", ()),
        )
    )
    assert in_countries(person, ["US"])
    assert not in_countries(person, ["CA"])


# --------------------------------------------------------------- filter string


def test_the_pool_filter_ors_topics_and_ands_the_rest():
    built = pool_filter(["T10001", "T10002"], ["US"])
    assert "topics.id:T10001|T10002" in built
    assert f"works_count:>{MIN_WORKS - 1}" in built
    assert "affiliations.institution.country_code:US" in built
    assert built.count(",") == 2


def test_several_countries_are_ored():
    assert "country_code:US|CA" in pool_filter(["T10001"], ["US", "CA"])


def test_a_pool_with_no_topics_is_refused():
    with pytest.raises(ValueError, match="at least one topic"):
        pool_filter([], ["US"])


# --------------------------------------------------------------------- funnel


def test_the_funnel_counts_who_left_at_each_step():
    funnel = Funnel()
    funnel.record("candidates", "topics", 100)
    funnel.record("core topic share", "at least 0.25", 40)
    funnel.record("university", "education", 30)
    assert [s.kept for s in funnel.steps] == [100, 40, 30]
    assert [s.dropped for s in funnel.steps] == [0, 60, 10]
    assert [s.step for s in funnel.steps] == [1, 2, 3]


def test_the_funnel_csv_holds_counts_and_nothing_else(tmp_path):
    funnel = Funnel()
    funnel.record("candidates", "topics T10001|T10002", 100)
    funnel.record("university", "an affiliation of type education", 30)
    path = funnel.write_csv(tmp_path / "results" / "funnel.csv")

    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert rows[0]["kept"] == "100"
    assert rows[1]["dropped"] == "70"
    assert "A1000001" not in path.read_text(encoding="utf-8")


def test_the_guardrail_stops_a_funnel_row_that_names_somebody(tmp_path):
    funnel = Funnel()
    funnel.record("candidates", "dropped A1000001 by hand", 10)
    with pytest.raises(GuardrailViolation):
        funnel.write_csv(tmp_path / "results" / "funnel.csv")


# -------------------------------------------------------------------- storage


class Pages:
    """A mock OpenAlex that serves a fixed list of author pages."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        index = min(self.requests - 1, len(self.pages) - 1)
        results = self.pages[index]
        # A distinct cursor per page: the client refuses to replay one.
        nxt = f"cursor-{self.requests}" if self.requests < len(self.pages) else None
        return httpx.Response(
            200, json={"results": results, "meta": {"next_cursor": nxt}}
        )

    def client(self, tmp_path, name=".cache"):
        return OpenAlexClient(
            mailto="tester@example.edu",
            cache_dir=tmp_path / name,
            transport=httpx.MockTransport(self.handler),
            requests_per_second=0,
        )


def test_the_pool_is_written_gzipped_one_person_per_line(tmp_path):
    server = Pages([[raw_author(ident="A1000001"), raw_author(ident="A1000002")]])
    dest = tmp_path / "data" / POOL_FILENAME
    written = harvest_pool(server.client(tmp_path), TOPICS, ["US"], dest)

    assert written == 2
    with gzip.open(dest, "rt", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert [row["author_id"] for row in lines] == ["A1000001", "A1000002"]


def test_the_pool_follows_every_page(tmp_path):
    server = Pages(
        [[raw_author(ident="A1000001")], [raw_author(ident="A1000002")], []]
    )
    dest = tmp_path / "data" / POOL_FILENAME
    assert harvest_pool(server.client(tmp_path), TOPICS, ["US"], dest) == 2


def test_a_repeated_author_is_only_written_once(tmp_path):
    server = Pages([[raw_author(ident="A1000001"), raw_author(ident="A1000001")]])
    dest = tmp_path / "data" / POOL_FILENAME
    assert harvest_pool(server.client(tmp_path), TOPICS, ["US"], dest) == 1


def test_a_gathered_pool_is_not_gathered_again(tmp_path):
    server = Pages([[raw_author(ident="A1000001")]])
    dest = tmp_path / "data" / POOL_FILENAME
    client = server.client(tmp_path)
    harvest_pool(client, TOPICS, ["US"], dest)
    before = client.request_count

    again = harvest_pool(client, TOPICS, ["US"], dest)
    assert again == 1
    assert client.request_count == before


def test_refresh_gathers_the_pool_again(tmp_path):
    server = Pages([[raw_author(ident="A1000001")]])
    dest = tmp_path / "data" / POOL_FILENAME
    client = server.client(tmp_path)
    harvest_pool(client, TOPICS, ["US"], dest)
    harvest_pool(client, TOPICS, ["US"], dest, refresh=True)
    assert dest.exists()


def test_a_half_written_pool_never_appears(tmp_path):
    """A file that exists is a file that finished, so a resumed run trusts it."""

    def boom(_request):
        raise httpx.ConnectError("network died")

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(boom),
        requests_per_second=0,
        sleep=lambda _s: None,
        max_tries=1,
    )
    dest = tmp_path / "data" / POOL_FILENAME
    with pytest.raises(OpenAlexError):
        harvest_pool(client, TOPICS, ["US"], dest)
    assert not dest.exists()


def test_the_pool_streams_back_off_disk(tmp_path):
    server = Pages([[raw_author(ident="A1000001", name="Alex Roe")]])
    dest = tmp_path / "data" / POOL_FILENAME
    harvest_pool(server.client(tmp_path), TOPICS, ["US"], dest)
    people = list(load_pool(dest))
    assert [p.name for p in people] == ["Alex Roe"]


# ------------------------------------------------------------------ screening


def test_screening_drops_people_off_the_subfield(config_dict):
    config = config_for(config_dict, core_topic_share_min=0.25)
    people = [
        candidate(ident="A1000001", topics=(("T10001", 8, 0.8), ("T9", 2, 0.2))),
        candidate(ident="A1000002", topics=(("T10001", 1, 0.1), ("T9", 9, 0.9))),
    ]
    funnel = Funnel()
    kept = screen_pool(people, config, funnel)
    assert [p.author_id for p in kept] == ["A1000001"]
    assert funnel.steps[1].label == "core topic share"
    assert funnel.steps[1].dropped == 1


def test_screening_drops_people_with_no_university(config_dict):
    config = config_for(config_dict)
    people = [
        candidate(ident="A1000001"),
        candidate(
            ident="A1000002", affiliations=(("00000000a", "US", "company", ()),)
        ),
    ]
    kept = screen_pool(people, config, Funnel())
    assert [p.author_id for p in kept] == ["A1000001"]


def test_screening_records_every_step_in_order(config_dict):
    config = config_for(config_dict)
    funnel = Funnel()
    screen_pool([candidate()], config, funnel)
    assert [s.label for s in funnel.steps] == [
        "candidates",
        "core topic share",
        "university",
    ]


def test_a_cached_pool_is_rescreened_against_the_current_countries(config_dict):
    """The API filter cannot re-run, so the country rule is checked locally too."""
    config = config_for(config_dict, countries=["CA"])
    kept = screen_pool([candidate()], config, Funnel())
    assert kept == []


# ----------------------------------------------------------------- end to end


def test_build_pool_writes_the_pool_and_the_funnel(tmp_path, config_dict):
    config = config_for(config_dict)
    server = Pages(
        [
            [
                raw_author(ident="A1000001"),
                raw_author(
                    ident="A1000002", affiliations=(("00000000a", "US", "company", ()),)
                ),
                raw_author(ident="A1000003", topics=(("T9", 40, 1.0),)),
            ]
        ]
    )
    result = build_pool(
        server.client(tmp_path),
        config,
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
    )

    assert result.pool_size == 3
    assert [p.author_id for p in result.kept] == ["A1000001"]
    assert result.pool_path.exists()

    rows = list(csv.DictReader(result.funnel_path.read_text(encoding="utf-8").splitlines()))
    assert [r["label"] for r in rows] == ["candidates", "core topic share", "university"]
    assert [r["kept"] for r in rows] == ["3", "2", "1"]


def test_build_pool_never_writes_a_name_into_results(tmp_path, config_dict):
    config = config_for(config_dict)
    server = Pages([[raw_author(ident="A1000001", name="Alex Roe")]])
    result = build_pool(
        server.client(tmp_path),
        config,
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
    )
    written = result.funnel_path.read_text(encoding="utf-8")
    assert "Alex Roe" not in written
    assert "A1000001" not in written


def test_build_pool_reports_progress(tmp_path, config_dict):
    config = config_for(config_dict)
    server = Pages([[raw_author()]])
    said: list[str] = []
    build_pool(
        server.client(tmp_path),
        config,
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
        on_progress=said.append,
    )
    joined = "\n".join(said)
    assert "Gathering candidates" in joined
    assert "requests" in joined


def test_the_pool_size_is_estimated_in_one_request(tmp_path):
    class Counted:
        def handler(self, request):
            return httpx.Response(200, json={"results": [], "meta": {"count": 4321}})

    server = Counted()
    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(server.handler),
        requests_per_second=0,
    )
    assert estimate_pool_size(client, TOPICS, ["US"]) == 4321
    assert client.request_count == 1


def test_the_harvest_says_how_big_it_will_be(tmp_path):
    server = Pages([[raw_author()]])
    said: list[str] = []
    harvest_pool(
        server.client(tmp_path),
        TOPICS,
        ["US"],
        tmp_path / "data" / POOL_FILENAME,
        on_progress=said.append,
    )
    assert any("people to gather" in line for line in said)
