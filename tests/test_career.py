"""Career-start estimation (TASKS.md task 4).

A wrong start year moves someone to the wrong career year and corrupts the
norms quietly, so these tests are mostly about what the rule refuses to do.
Every person here is invented.
"""

from __future__ import annotations

import gzip
import json

import httpx

from tenuretrack.career import (
    AFFILIATION_LED,
    FIRST_LED_MINUS_ONE,
    HIGH,
    LOW,
    NO_RULE,
    STARTS_FILENAME,
    StartEstimate,
    build_starts,
    estimate_start,
    estimate_starts,
    load_starts,
    plausible_years,
    screen_starts,
)
from tenuretrack.config import build_config
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.pool import Funnel, parse_candidate

PHD = "01phd0000"
JOB = "02job0000"
SECOND_JOB = "03two0000"
ARTICLES = ["article"]
ME = "A1000001"


# ------------------------------------------------------------------- builders


def paper(year, ror, position="middle", corresponding=False, ident=None, who=ME):
    """One work with this person on it, at one institution."""
    return {
        "id": f"https://openalex.org/{ident or f'W{year}{ror}{position}'}",
        "doi": f"https://doi.org/10.1/{year}-{ror}-{position}",
        "title": f"Paper {year}",
        "publication_year": year,
        "type": "article",
        "cited_by_count": 1,
        "primary_location": {"source": {"display_name": "Journal", "type": "journal"}},
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{who}"},
                "author_position": position,
                "is_corresponding": corresponding,
                "institutions": [{"ror": f"https://ror.org/{ror}"}],
            }
        ],
    }


def works(*raws):
    from tenuretrack.works import parse_work

    return [parse_work(r) for r in raws]


def trainee_then_faculty():
    """The clean case: first-author papers at a PhD lab, then a group of one's own."""
    return works(
        paper(2004, PHD, "first"),
        paper(2005, PHD, "first"),
        paper(2006, PHD, "middle"),
        paper(2012, JOB, "middle"),
        paper(2013, JOB, "last"),
        paper(2015, JOB, "last"),
    )


def candidate(author_id=ME, years=(2004, 2013), ror=JOB):
    return parse_candidate(
        {
            "id": f"https://openalex.org/{author_id}",
            "display_name": "Alex Roe",
            "works_count": 30,
            "topics": [{"id": "https://openalex.org/T10001", "count": 30}],
            "affiliations": [
                {
                    "institution": {
                        "ror": f"https://ror.org/{ror}",
                        "country_code": "US",
                        "type": "education",
                    },
                    "years": list(years),
                }
            ],
        }
    )


def config_for(config_dict, **cohort):
    config_dict["cohort"].update(cohort)
    return build_config(config_dict)


# ----------------------------------------------------------------- the rules


def test_the_clean_case_is_the_first_year_at_the_place_they_led_from():
    estimate = estimate_start(trainee_then_faculty(), [ME], ARTICLES)
    assert estimate.year == 2012
    assert estimate.rule == AFFILIATION_LED
    assert estimate.confidence == HIGH
    assert estimate.institution_ror == JOB
    assert estimate.led_papers == 2


def test_a_corresponding_flag_counts_as_leading():
    record = works(
        paper(2004, PHD, "first"),
        paper(2012, JOB, "middle"),
        paper(2013, JOB, "middle", corresponding=True),
        paper(2014, JOB, "middle", corresponding=True),
    )
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.year == 2012
    assert estimate.confidence == HIGH


def test_one_led_paper_is_not_a_group():
    record = works(
        paper(2004, PHD, "first"),
        paper(2012, JOB, "middle"),
        paper(2013, JOB, "last"),
    )
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.rule == FIRST_LED_MINUS_ONE
    assert estimate.confidence == LOW
    assert estimate.year == 2012


def test_someone_who_never_moved_cannot_be_placed_confidently():
    """PhD and faculty job at one institution look identical from bylines."""
    record = works(
        paper(2004, JOB, "first"),
        paper(2012, JOB, "last"),
        paper(2013, JOB, "last"),
    )
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.confidence == LOW
    assert "cannot be told apart" in estimate.note


def test_someone_who_never_led_anything_is_not_placed():
    record = works(paper(2010, PHD, "first"), paper(2012, PHD, "middle"))
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.year is None
    assert estimate.rule == NO_RULE
    assert not estimate.is_usable


def test_an_empty_record_is_not_placed():
    estimate = estimate_start([], [ME], ARTICLES)
    assert estimate.year is None
    assert "no journal articles" in estimate.note


def test_preprints_do_not_establish_a_start():
    preprint = paper(2009, JOB, "last")
    preprint["type"] = "preprint"
    record = works(paper(2004, PHD, "first"), preprint, *[
        paper(2013, JOB, "last"), paper(2014, JOB, "last")
    ])
    assert estimate_start(record, [ME], ARTICLES).year == 2013


def test_someone_who_moved_between_two_faculty_jobs_starts_at_the_first():
    record = works(
        paper(2004, PHD, "first"),
        paper(2010, JOB, "last"),
        paper(2011, JOB, "last"),
        paper(2019, SECOND_JOB, "last"),
        paper(2020, SECOND_JOB, "last"),
    )
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.year == 2010
    assert estimate.institution_ror == JOB


def test_a_paper_carrying_both_institutions_does_not_break_the_split():
    """A byline listing the old lab and the new job in the move year."""
    both = paper(2012, JOB, "middle")
    both["authorships"][0]["institutions"] = [
        {"ror": f"https://ror.org/{PHD}"},
        {"ror": f"https://ror.org/{JOB}"},
    ]
    record = works(
        paper(2004, PHD, "first"),
        paper(2005, PHD, "first"),
        both,
        paper(2013, JOB, "last"),
        paper(2014, JOB, "last"),
    )
    estimate = estimate_start(record, [ME], ARTICLES)
    assert estimate.year == 2012
    assert estimate.institution_ror == JOB


def test_a_start_is_never_earlier_than_the_first_paper_at_that_place():
    estimate = estimate_start(trainee_then_faculty(), [ME], ARTICLES)
    assert estimate.year is not None
    first_at_job = min(
        w.year for w in trainee_then_faculty() if JOB in str(w.bylines[0].institution_rors)
    )
    assert estimate.year == first_at_job


# ------------------------------------------------------------- the pre-filter


def test_a_record_that_ends_before_the_window_is_not_worth_asking_about():
    assert not plausible_years(candidate(years=(1998, 2004)), (2008, 2018))


def test_a_record_that_starts_after_the_window_is_not_worth_asking_about():
    assert not plausible_years(candidate(years=(2020, 2024)), (2008, 2018))


def test_a_record_spanning_the_window_is_worth_asking_about():
    assert plausible_years(candidate(years=(2004, 2020)), (2008, 2018))


def test_a_record_with_no_years_at_all_is_dropped():
    assert not plausible_years(candidate(years=()), (2008, 2018))


def test_the_pre_filter_only_drops_people_the_rule_would_drop_anyway():
    """Its whole justification: it saves requests without changing the cohort."""
    late = works(paper(2021, JOB, "last"), paper(2022, JOB, "last"))
    estimate = estimate_start(late, [ME], ARTICLES)
    assert not (2008 <= (estimate.year or 0) <= 2018 and estimate.is_usable)


# ------------------------------------------------------------------ screening


def test_screening_keeps_confident_starts_inside_the_window(config_dict):
    config = config_for(config_dict, start_window=[2008, 2018])
    people = [candidate("A1000001"), candidate("A1000002"), candidate("A1000003")]
    estimates = {
        "A1000001": StartEstimate("A1000001", 2012, AFFILIATION_LED, HIGH),
        "A1000002": StartEstimate("A1000002", 2021, AFFILIATION_LED, HIGH),
        "A1000003": StartEstimate("A1000003", 2012, FIRST_LED_MINUS_ONE, LOW),
    }
    funnel = Funnel()
    kept = screen_starts(people, estimates, config, funnel)
    assert [c.author_id for c, _ in kept] == ["A1000001"]
    assert funnel.steps[0].kept == 2  # two placed confidently
    assert funnel.steps[1].kept == 1  # one of them inside the window


def test_a_candidate_with_no_estimate_at_all_is_dropped(config_dict):
    kept = screen_starts([candidate()], {}, build_config(config_dict), Funnel())
    assert kept == []


def test_the_window_edges_are_inclusive(config_dict):
    config = config_for(config_dict, start_window=[2008, 2018])
    people = [candidate("A1000001"), candidate("A1000002")]
    estimates = {
        "A1000001": StartEstimate("A1000001", 2008, AFFILIATION_LED, HIGH),
        "A1000002": StartEstimate("A1000002", 2018, AFFILIATION_LED, HIGH),
    }
    kept = screen_starts(people, estimates, config, Funnel())
    assert len(kept) == 2


# -------------------------------------------------------------------- storage


class WorksServer:
    """A mock OpenAlex serving one page of works per batched query."""

    def __init__(self, by_author):
        self.by_author = by_author
        self.queries: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.queries.append(url)
        results = [
            raw
            for author, raws in self.by_author.items()
            if author in url
            for raw in raws
        ]
        return httpx.Response(
            200, json={"results": results, "meta": {"next_cursor": None}}
        )

    def client(self, tmp_path):
        return OpenAlexClient(
            mailto="tester@example.edu",
            cache_dir=tmp_path / ".cache",
            transport=httpx.MockTransport(self.handler),
            requests_per_second=0,
        )


def test_starts_are_written_one_person_per_line(tmp_path, config_dict):
    server = WorksServer(
        {
            ME: [
                paper(2004, PHD, "first"),
                paper(2012, JOB, "middle"),
                paper(2013, JOB, "last"),
                paper(2014, JOB, "last"),
            ]
        }
    )
    dest = tmp_path / "data" / STARTS_FILENAME
    estimates = estimate_starts(
        server.client(tmp_path), [candidate()], build_config(config_dict), dest
    )
    assert estimates[ME].year == 2012

    with gzip.open(dest, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    assert rows[0]["author_id"] == ME
    assert rows[0]["rule"] == AFFILIATION_LED


def test_estimates_round_trip_through_disk(tmp_path, config_dict):
    server = WorksServer({ME: [paper(2013, JOB, "last")]})
    dest = tmp_path / "data" / STARTS_FILENAME
    written = estimate_starts(
        server.client(tmp_path), [candidate()], build_config(config_dict), dest
    )
    assert load_starts(dest) == written


def test_a_finished_estimate_file_is_not_rebuilt(tmp_path, config_dict):
    server = WorksServer({ME: [paper(2013, JOB, "last")]})
    client = server.client(tmp_path)
    dest = tmp_path / "data" / STARTS_FILENAME
    estimate_starts(client, [candidate()], build_config(config_dict), dest)
    before = client.request_count

    estimate_starts(client, [candidate()], build_config(config_dict), dest)
    assert client.request_count == before


def test_people_are_asked_about_fifty_at_a_time(tmp_path, config_dict):
    people = [candidate(f"A100{i:04d}") for i in range(120)]
    server = WorksServer({})
    client = server.client(tmp_path)
    estimate_starts(
        client, people, build_config(config_dict), tmp_path / "data" / STARTS_FILENAME
    )
    assert len(server.queries) == 3  # 120 people, 50 per query
    assert client.request_count == 3


def test_the_query_asks_for_the_trainee_years_too(tmp_path, config_dict):
    server = WorksServer({})
    config = config_for(config_dict, start_window=[2008, 2018], horizon_years=6)
    estimate_starts(
        server.client(tmp_path),
        [candidate()],
        config,
        tmp_path / "data" / STARTS_FILENAME,
    )
    assert "publication_year%3A1993-2024" in server.queries[0]


def test_a_paper_shared_by_two_candidates_counts_for_both(tmp_path, config_dict):
    shared = paper(2013, JOB, "last", who="A1000001")
    shared["authorships"].append(
        {
            "author": {"id": "https://openalex.org/A1000002"},
            "author_position": "first",
            "is_corresponding": False,
            "institutions": [{"ror": f"https://ror.org/{JOB}"}],
        }
    )
    server = WorksServer({"A1000001": [shared]})
    estimates = estimate_starts(
        server.client(tmp_path),
        [candidate("A1000001"), candidate("A1000002")],
        build_config(config_dict),
        tmp_path / "data" / STARTS_FILENAME,
    )
    assert estimates["A1000001"].led_papers == 1
    assert estimates["A1000002"].rule == NO_RULE  # first author, never led


# ----------------------------------------------------------------- end to end


def test_build_starts_records_both_funnel_steps(tmp_path, config_dict):
    server = WorksServer(
        {
            ME: [
                paper(2004, PHD, "first"),
                paper(2012, JOB, "middle"),
                paper(2013, JOB, "last"),
                paper(2014, JOB, "last"),
            ]
        }
    )
    config = config_for(config_dict, start_window=[2008, 2018])
    funnel = Funnel()
    members = build_starts(
        server.client(tmp_path),
        [candidate(), candidate("A1000009", years=(2021, 2024))],
        config,
        funnel,
        data_dir=tmp_path / "data",
    )
    assert [s.label for s in funnel.steps] == [
        "plausible years",
        "career start estimated",
        "start in window",
    ]
    assert funnel.steps[0].kept == 1  # the 2021 starter never costs a request
    assert [c.author_id for c, _ in members] == [ME]


def test_build_starts_writes_nothing_into_results(tmp_path, config_dict):
    server = WorksServer({ME: [paper(2013, JOB, "last")]})
    build_starts(
        server.client(tmp_path),
        [candidate()],
        build_config(config_dict),
        Funnel(),
        data_dir=tmp_path / "data",
    )
    assert not (tmp_path / "results").exists()
    assert (tmp_path / "data" / STARTS_FILENAME).exists()
