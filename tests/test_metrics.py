"""Per-person metrics and cohort quartiles (TASKS.md task 5).

The numbers here are what the whole tool reports, so these tests are mostly
about the claims being true: people are the unit of analysis, quartiles are not
averages, missing venue data stays missing, and nothing identifying reaches
`results/`.
"""

from __future__ import annotations

import csv

import httpx
import numpy as np
import pytest

from tenuretrack.career import AFFILIATION_LED, HIGH, StartEstimate
from tenuretrack.config import build_config
from tenuretrack.guardrail import PRESCRIPTIVE_TERMS, GuardrailViolation
from tenuretrack.metrics import (
    METRICS,
    MemberMetrics,
    benchmark_table,
    bootstrap_quartiles,
    build_metrics,
    fetch_venue_impacts,
    h_index,
    member_metrics,
    top_quartile_cutoff,
    window_papers,
    write_benchmarks_csv,
    write_benchmarks_md,
)
from tenuretrack.openalex import OpenAlexClient
from tenuretrack.works import parse_work

ME = "A1000001"
ARTICLES = ["article"]


# ------------------------------------------------------------------- builders


def paper(year, position="middle", source="S100", citations=0, ident=None, kind="article"):
    return parse_work(
        {
            "id": f"https://openalex.org/{ident or f'W{year}{position}{source}{citations}'}",
            "doi": f"https://doi.org/10.1/{year}-{position}-{source}-{citations}",
            "title": f"Paper {year} {position} {citations}",
            "publication_year": year,
            "type": kind,
            "cited_by_count": citations,
            "primary_location": {
                "source": {
                    "id": f"https://openalex.org/{source}",
                    "display_name": f"Journal {source}",
                    "type": "journal",
                }
            },
            "authorships": [
                {
                    "author": {"id": f"https://openalex.org/{ME}"},
                    "author_position": position,
                    "is_corresponding": False,
                    "institutions": [],
                }
            ],
        }
    )


def config_for(config_dict, **cohort):
    config_dict["cohort"].update(cohort)
    return build_config(config_dict)


# -------------------------------------------------------------------- h-index


@pytest.mark.parametrize(
    ("citations", "expected"),
    [
        ([], 0),
        ([0, 0, 0], 0),
        ([1], 1),
        ([10, 8, 5, 4, 3], 4),
        ([25, 8, 5, 3, 3], 3),
        ([100], 1),
        ([3, 3, 3], 3),
    ],
)
def test_h_index(citations, expected):
    assert h_index(citations) == expected


def test_h_index_does_not_care_about_order():
    assert h_index([3, 10, 1, 8]) == h_index([10, 8, 3, 1])


# --------------------------------------------------------------- the window


def test_the_window_is_career_years_one_through_n():
    works = [paper(y) for y in range(2008, 2020)]
    got = window_papers(works, 2010, 6, ARTICLES)
    assert sorted(w.year for w in got) == [2010, 2011, 2012, 2013, 2014, 2015]


def test_year_one_is_the_year_the_appointment_began():
    assert len(window_papers([paper(2010)], 2010, 1, ARTICLES)) == 1


def test_the_window_excludes_anything_that_is_not_a_journal_article():
    works = [paper(2010), paper(2011, kind="preprint"), paper(2012, kind="book-chapter")]
    assert len(window_papers(works, 2010, 6, ARTICLES)) == 1


# ------------------------------------------------------------ one person


def test_a_persons_record_is_counted_correctly():
    works = [
        paper(2010, "last", "S1", 10),
        paper(2011, "last", "S1", 5),
        paper(2012, "first", "S2", 3),
        paper(2013, "middle", "S2", 1),
    ]
    got = member_metrics(works, [ME], 2010, 6, ARTICLES, {}, None)
    assert got.pubs == 4
    assert got.led == 2
    assert got.lead_share == pytest.approx(0.5)
    assert got.citations == 19
    assert got.h_index == 3


def test_a_person_with_no_papers_yet_has_no_share_rather_than_zero():
    """A share of nothing is not applicable, and averaging a zero in would drag
    the cohort down with a number that means "no data"."""
    got = member_metrics([], [ME], 2010, 6, ARTICLES, {}, None)
    assert got.pubs == 0
    assert got.lead_share is None
    assert got.venue_impact_median is None
    assert got.top_quartile_share is None


def test_venue_impact_is_the_median_over_papers_with_a_known_venue():
    works = [paper(2010, source="S1"), paper(2011, source="S2"), paper(2012, source="S3")]
    impacts = {"S1": 1.0, "S2": 5.0}  # S3 unknown
    got = member_metrics(works, [ME], 2010, 6, ARTICLES, impacts, None)
    assert got.venue_impact_median == pytest.approx(3.0)


def test_a_venue_with_no_impact_figure_is_left_out_not_counted_as_zero():
    works = [paper(2010, source="S1"), paper(2011, source="S404")]
    got = member_metrics(works, [ME], 2010, 6, ARTICLES, {"S1": 4.0}, None)
    assert got.venue_impact_median == pytest.approx(4.0)


def test_top_quartile_share_is_over_papers_whose_venue_is_known():
    works = [
        paper(2010, source="S1"),
        paper(2011, source="S2"),
        paper(2012, source="S404"),
    ]
    got = member_metrics(works, [ME], 2010, 6, ARTICLES, {"S1": 9.0, "S2": 1.0}, 5.0)
    assert got.top_quartile_share == pytest.approx(0.5)


def test_a_corresponding_author_counts_as_leading():
    raw = paper(2010, "middle")
    work = parse_work(
        {
            "id": "https://openalex.org/Wx",
            "doi": "https://doi.org/10.1/x",
            "publication_year": 2010,
            "type": "article",
            "cited_by_count": 0,
            "primary_location": {"source": {"id": "https://openalex.org/S1", "type": "journal"}},
            "authorships": [
                {
                    "author": {"id": f"https://openalex.org/{ME}"},
                    "author_position": "middle",
                    "is_corresponding": True,
                    "institutions": [],
                }
            ],
        }
    )
    assert member_metrics([raw, work], [ME], 2010, 6, ARTICLES, {}, None).led == 1


# ------------------------------------------------------------- venue cutoff


def test_the_cutoff_is_the_seventy_fifth_percentile_of_cohort_venues():
    papers = [paper(2010, source=f"S{i}") for i in range(1, 5)]
    impacts = {"S1": 1.0, "S2": 2.0, "S3": 3.0, "S4": 4.0}
    assert top_quartile_cutoff(papers, impacts) == pytest.approx(3.25)


def test_too_few_venues_to_speak_of_a_quartile():
    papers = [paper(2010, source="S1")]
    assert top_quartile_cutoff(papers, {"S1": 1.0}) is None


# ------------------------------------------------------- quartiles and the CI


def test_quartiles_are_quartiles_not_an_average():
    """One prolific person must not become the cohort's median."""
    values = [1.0] * 20 + [1000.0]
    got = bootstrap_quartiles(values, "pubs", 6, iterations=200)
    assert got.p50 == pytest.approx(1.0)
    assert np.mean(values) > 40  # the mean would have said something else


def test_the_confidence_interval_brackets_the_estimate():
    rng = np.random.default_rng(7)
    values = list(rng.normal(10, 3, size=200))
    got = bootstrap_quartiles(values, "pubs", 6, iterations=500, rng=rng)
    assert got.p50_lo <= got.p50 <= got.p50_hi
    assert got.p25_lo <= got.p25 <= got.p25_hi
    assert got.p75_lo <= got.p75 <= got.p75_hi


def test_a_bigger_cohort_gives_a_tighter_interval():
    rng = np.random.default_rng(11)
    small = bootstrap_quartiles(
        list(rng.normal(10, 3, size=20)), "pubs", 6, iterations=500, rng=rng
    )
    large = bootstrap_quartiles(
        list(rng.normal(10, 3, size=500)), "pubs", 6, iterations=500, rng=rng
    )
    assert (large.p50_hi - large.p50_lo) < (small.p50_hi - small.p50_lo)


def test_the_bootstrap_is_reproducible():
    values = [float(i) for i in range(50)]
    first = bootstrap_quartiles(
        values, "pubs", 6, iterations=200, rng=np.random.default_rng(3)
    )
    second = bootstrap_quartiles(
        values, "pubs", 6, iterations=200, rng=np.random.default_rng(3)
    )
    assert first == second


def test_missing_values_are_dropped_and_the_count_says_so():
    got = bootstrap_quartiles([1.0, None, 2.0, None, 3.0, 4.0, 5.0], "x", 6, iterations=50)
    assert got.n == 5


def test_a_cell_too_small_to_publish_is_withheld():
    """A quartile over three people can identify them."""
    got = bootstrap_quartiles([1.0, 2.0, 3.0], "pubs", 6, iterations=50, min_cell_size=5)
    assert got.suppressed
    assert got.n == 3
    assert got.p50 is None


# ---------------------------------------------------------------- the table


def members(horizon, values):
    return [
        MemberMetrics(author_id=f"A{i}", horizon=horizon, pubs=v, citations=v * 10)
        for i, v in enumerate(values)
    ]


def test_the_table_covers_every_metric_at_every_horizon(config_dict):
    config = config_for(config_dict, horizon_years=3, bootstrap_iterations=100)
    per_member = {h: members(h, range(10)) for h in (1, 2, 3)}
    rows = benchmark_table(per_member, config)
    assert {r.horizon for r in rows} == {1, 2, 3}
    assert {r.metric for r in rows} == {m.key for m in METRICS}


# ---------------------------------------------------------------- the writers


def rows_for(config, n=10):
    per_member = {h: members(h, range(n)) for h in config.cohort.horizons}
    return benchmark_table(per_member, config)


def test_the_csv_holds_aggregates_and_passes_the_guardrail(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=2, bootstrap_iterations=100)
    path = write_benchmarks_csv(rows_for(config), tmp_path / "results" / "benchmarks.csv")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert {r["career_year"] for r in rows} == {"1", "2"}
    assert "A1000001" not in path.read_text(encoding="utf-8")


def test_a_withheld_cell_writes_no_numbers(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    path = write_benchmarks_csv(rows_for(config, n=3), tmp_path / "b.csv")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert all(r["p50"] == "" for r in rows), "no numbers survive suppression"
    pubs = next(r for r in rows if r["metric"] == "pubs")
    assert pubs["people"] == "3", "the count is still reported, only the values are not"


def test_the_report_reads_as_description_not_instruction(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=2, bootstrap_iterations=100)
    path = write_benchmarks_md(
        rows_for(config), tmp_path / "benchmarks.md", config=config, cohort_size=200
    )
    text = path.read_text(encoding="utf-8")
    for term in PRESCRIPTIVE_TERMS:
        assert term not in text.lower(), f"{term!r} turns a description into an instruction"
    assert "not a standard" in text
    assert "median" in text.lower()


def test_the_report_carries_its_caveats(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=2, bootstrap_iterations=100)
    path = write_benchmarks_md(
        rows_for(config), tmp_path / "b.md", config=config, cohort_size=200
    )
    text = path.read_text(encoding="utf-8")
    assert "Teaching" in text
    assert "OpenAlex" in text
    assert "within this cohort" in text
    assert "confidence interval" in text


def test_a_small_cohort_is_flagged_loudly(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    path = write_benchmarks_md(
        rows_for(config), tmp_path / "b.md", config=config, cohort_size=12
    )
    assert "indicative only" in path.read_text(encoding="utf-8")


def test_a_big_cohort_is_not_flagged(tmp_path, config_dict):
    config = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    path = write_benchmarks_md(
        rows_for(config), tmp_path / "b.md", config=config, cohort_size=400
    )
    assert "indicative only" not in path.read_text(encoding="utf-8")


def test_the_writers_refuse_to_emit_an_identifier(tmp_path, config_dict):
    """The guardrail runs on the file itself, not on good intentions."""
    config = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    config_dict["subfield"]["label"] = "work by A5023888391"
    leaky = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    with pytest.raises(GuardrailViolation):
        write_benchmarks_md(
            rows_for(config), tmp_path / "b.md", config=leaky, cohort_size=100
        )


# -------------------------------------------------------------------- venues


def test_venue_impacts_are_fetched_in_batches(tmp_path):
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"https://openalex.org/S{i}",
                        "summary_stats": {"2yr_mean_citedness": float(i)},
                    }
                    for i in range(1, 4)
                ]
            },
        )

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(handler),
        requests_per_second=0,
    )
    impacts = fetch_venue_impacts(client, [f"S{i}" for i in range(1, 121)])
    assert len(seen) == 3  # 120 sources, 50 per query
    assert impacts["S1"] == pytest.approx(1.0)


def test_a_venue_with_no_impact_figure_is_simply_absent(tmp_path):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "https://openalex.org/S1", "summary_stats": {}},
                    {
                        "id": "https://openalex.org/S2",
                        "summary_stats": {"2yr_mean_citedness": 2.5},
                    },
                ]
            },
        )

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(handler),
        requests_per_second=0,
    )
    impacts = fetch_venue_impacts(client, ["S1", "S2"])
    assert "S1" not in impacts
    assert impacts["S2"] == pytest.approx(2.5)


def test_no_venues_means_no_request(tmp_path):
    def handler(_request):
        raise AssertionError("should not ask about nothing")

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(handler),
        requests_per_second=0,
    )
    assert fetch_venue_impacts(client, []) == {}


# ----------------------------------------------------------------- end to end


def test_build_metrics_holds_the_venue_cutoff_fixed_across_horizons(config_dict):
    """A cutoff that moved per horizon would make year 3 and year 6 incomparable."""
    config = config_for(config_dict, horizon_years=3, bootstrap_iterations=100)
    works = {
        "A1": [paper(2010 + i, "last", f"S{i + 1}", 5) for i in range(3)],
        "A2": [paper(2010 + i, "first", f"S{i + 1}", 2) for i in range(3)],
    }
    starts = {
        a: StartEstimate(a, 2010, AFFILIATION_LED, HIGH) for a in ("A1", "A2")
    }
    impacts = {"S1": 1.0, "S2": 4.0, "S3": 9.0}
    per_member, rows, cutoff, headline = build_metrics(works, starts, config, impacts)

    assert cutoff is not None
    assert set(per_member) == {1, 2, 3}
    # Year 1 sees only S1, but the cutoff came from the whole headline window.
    assert cutoff > 1.0
    assert headline, "the venue list is built from these"


def test_people_without_a_start_are_left_out(config_dict):
    config = config_for(config_dict, horizon_years=1, bootstrap_iterations=100)
    works = {"A1": [paper(2010)], "A2": [paper(2010)]}
    starts = {"A1": StartEstimate("A1", 2010, AFFILIATION_LED, HIGH)}
    per_member, _, _, _ = build_metrics(works, starts, config, {})
    assert [m.author_id for m in per_member[1]] == ["A1"]


# ------------------------------------------ reading papers without refetching


def test_the_cohorts_papers_come_off_disk_not_the_network(tmp_path, config_dict):
    """Removing one candidate reshuffles every batch, so leaning on the request
    cache alone silently re-downloads the lot. Measured at 1,236 requests."""
    import gzip
    import json

    from tenuretrack.career import WORKS_FILENAME
    from tenuretrack.metrics import collect_member_works
    from tenuretrack.works import only_bylines_of, work_to_row

    data = tmp_path / "data"
    data.mkdir()
    with gzip.open(data / WORKS_FILENAME, "wt", encoding="utf-8") as handle:
        for author in ("A1", "A2"):
            works = [only_bylines_of(paper(2010, "last"), [ME])]
            handle.write(
                json.dumps({"author_id": author, "works": [work_to_row(w) for w in works]})
                + "\n"
            )

    def explode(_request):
        raise AssertionError("papers must come off disk, not the network")

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(explode),
        requests_per_second=0,
    )
    got = collect_member_works(
        client, [], ["A1"], config_for(config_dict), data_dir=data
    )
    assert set(got) == {"A1"}
    assert client.request_count == 0


def test_it_falls_back_to_the_network_if_the_data_dir_was_cleared(tmp_path, config_dict):
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"results": [], "meta": {"next_cursor": None}})

    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(handler),
        requests_per_second=0,
    )
    from tenuretrack.metrics import collect_member_works

    collect_member_works(
        client, ["A1"], ["A1"], config_for(config_dict), data_dir=tmp_path / "gone"
    )
    assert calls, "with no stored papers it has to ask"
