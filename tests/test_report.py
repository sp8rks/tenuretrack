"""The subject comparison and the report (TASKS.md task 6).

The report is the thing a person reads about their own career, so most of these
tests are about what it refuses to say: no judgement words, no citation
comparison, no cohort member named, and no comparison across mismatched career
years.
"""

from __future__ import annotations

import pytest

from tenuretrack.config import build_config
from tenuretrack.guardrail import PRESCRIPTIVE_TERMS, GuardrailViolation
from tenuretrack.metrics import MemberMetrics, Quartiles
from tenuretrack.pool import Funnel
from tenuretrack.report import (
    ABOVE_P75,
    AT_MEDIAN,
    BELOW_P25,
    MEDIAN_TO_P75,
    P25_TO_MEDIAN,
    comparison_horizon,
    place_subject,
    position_of,
    top_venues,
    write_report,
)
from tenuretrack.works import parse_work

ME = "A1000001"


def quartiles(metric="pubs", horizon=6, p25=5.0, p50=10.0, p75=20.0, **kwargs):
    return Quartiles(
        metric=metric, horizon=horizon, n=100, p25=p25, p50=p50, p75=p75, **kwargs
    )


def paper(year=2020, source="S1", name="Journal of Things"):
    return parse_work(
        {
            "id": f"https://openalex.org/W{year}{source}",
            "doi": f"https://doi.org/10.1/{year}-{source}",
            "publication_year": year,
            "type": "article",
            "cited_by_count": 3,
            "primary_location": {
                "source": {
                    "id": f"https://openalex.org/{source}",
                    "display_name": name,
                    "type": "journal",
                }
            },
            "authorships": [
                {
                    "author": {"id": f"https://openalex.org/{ME}"},
                    "author_position": "last",
                    "is_corresponding": False,
                    "institutions": [{"ror": "https://ror.org/03r0ha626"}],
                }
            ],
        }
    )


# ------------------------------------------------------- the comparison year


@pytest.mark.parametrize(
    ("career_year", "expected"), [(1, 1), (4, 4), (6, 6), (11, 6), (30, 6)]
)
def test_the_comparison_happens_at_a_matching_career_year(career_year, expected):
    assert comparison_horizon(career_year, 6) == expected


def test_someone_past_the_horizon_is_compared_at_the_horizon():
    """Placing a year-11 record against a year-6 cohort would credit five
    extra years of work to one side."""
    assert comparison_horizon(11, 6) == 6


def test_a_career_year_before_the_clock_starts_is_clamped():
    assert comparison_horizon(0, 6) == 1


# ------------------------------------------------------------------ position


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, BELOW_P25),
        (4.9, BELOW_P25),
        (5.0, P25_TO_MEDIAN),
        (9.0, P25_TO_MEDIAN),
        (10.0, AT_MEDIAN),
        (15.0, MEDIAN_TO_P75),
        (20.0, MEDIAN_TO_P75),
        (21.0, ABOVE_P75),
    ],
)
def test_position_is_a_location_in_the_distribution(value, expected):
    assert position_of(value, quartiles()) == expected


def test_a_missing_value_has_no_position():
    assert position_of(None, quartiles()) is None


def test_a_withheld_cell_gives_no_position():
    assert position_of(5.0, quartiles(suppressed=True)) is None


def test_every_position_word_is_descriptive():
    """CLAUDE.md rule 3: a position is about a distribution, not a person."""
    for phrase in (BELOW_P25, P25_TO_MEDIAN, AT_MEDIAN, MEDIAN_TO_P75, ABOVE_P75):
        for term in PRESCRIPTIVE_TERMS:
            assert term not in phrase.lower()


# ------------------------------------------------------------ citations rule


def test_citations_are_reported_but_never_placed():
    metrics = MemberMetrics(author_id=ME, horizon=6, pubs=10, citations=500)
    rows = [quartiles("pubs"), quartiles("citations", p25=100, p50=400, p75=900)]
    placements = {p.metric: p for p in place_subject(metrics, rows, 6)}

    assert placements["citations"].value == 500
    assert placements["citations"].position is None
    assert placements["citations"].compared is False
    assert placements["pubs"].position is not None


# ------------------------------------------------------------------- venues


def test_top_venues_counts_across_the_whole_cohort():
    papers = [
        paper(source="S1", name="Chem Mater"),
        paper(2021, "S1", "Chem Mater"),
        paper(source="S2", name="Nano Letters"),
    ]
    got = top_venues(papers, {"S1": 9.0, "S2": 3.0}, cutoff=5.0)
    assert got[0][0] == "Chem Mater"
    assert got[0][1] == 2
    assert got[0][3] is True  # above the cutoff
    assert got[1][3] is False


def test_a_venue_with_no_impact_is_listed_without_one():
    got = top_venues([paper(source="S9", name="Unknown Journal")], {}, cutoff=5.0)
    assert got[0][2] is None
    assert got[0][3] is False


def test_the_venue_list_names_venues_and_never_people():
    papers = [paper(source="S1", name="Chem Mater")]
    for name, _count, _impact, _top in top_venues(papers, {"S1": 1.0}, 1.0):
        assert not name.startswith("A")


# ------------------------------------------------------------------ the file


def written_report(tmp_path, config_dict, **overrides):
    config = build_config(config_dict)
    metrics = overrides.pop(
        "metrics",
        MemberMetrics(
            author_id=ME,
            horizon=6,
            pubs=18,
            led=7,
            lead_share=0.39,
            citations=640,
            h_index=12,
            venue_impact_median=5.1,
            top_quartile_share=0.44,
        ),
    )
    rows = [quartiles(m, 6) for m in ("pubs", "led", "lead_share", "citations",
                                      "h_index", "venue_impact_median",
                                      "top_quartile_share")]
    funnel = Funnel()
    funnel.record("candidates", "topics T10001", 5000)
    funnel.record("start in window", "estimated start 2008 to 2018", 900)
    defaults = dict(
        config=config,
        horizon=6,
        career_year=11,
        final_year_incomplete=False,
        extension=0,
        placements=place_subject(metrics, rows, 6),
        rows=rows,
        venues=[("Chemistry of Materials", 400, 9.1, True)],
        funnel=funnel,
        cohort_size=900,
        institutions=500,
    )
    defaults.update(overrides)
    return write_report(tmp_path / "results" / "report.md", **defaults)


def test_the_report_reads_as_description_not_instruction(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8").lower()
    for term in PRESCRIPTIVE_TERMS:
        assert term not in text, f"{term!r} turns a description into an instruction"


def test_the_report_names_only_the_subject(tmp_path, config_dict):
    path = written_report(tmp_path, config_dict)
    text = path.read_text(encoding="utf-8")
    assert "Jane Doe" in text
    assert "is not among them" in text


def test_the_report_says_why_citations_carry_no_position(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "not compared" in text
    assert "measure the calendar" in text


def test_the_report_explains_a_capped_comparison(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "is now in year 11 of it" in text
    assert "credit the extra years" in text


def test_a_subject_inside_the_clock_gets_no_capping_note(tmp_path, config_dict):
    text = written_report(
        tmp_path, config_dict, horizon=4, career_year=4
    ).read_text(encoding="utf-8")
    assert "credit the extra years" not in text


def test_the_report_carries_the_funnel_so_the_cohort_can_be_checked(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "How the cohort was built" in text
    assert "5000" in text
    assert "the one to question" in text


def test_the_report_lists_what_it_cannot_see(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "Teaching" in text
    assert "parental leave" in text
    assert "distinctive names" in text


def test_a_withheld_cell_is_shown_as_withheld(tmp_path, config_dict):
    metrics = MemberMetrics(author_id=ME, horizon=6, pubs=18)
    rows = [Quartiles(metric="pubs", horizon=6, n=2, suppressed=True)]
    config = build_config(config_dict)
    funnel = Funnel()
    funnel.record("candidates", "topics", 10)
    path = write_report(
        tmp_path / "report.md",
        config=config,
        horizon=6,
        career_year=6,
        final_year_incomplete=False,
        placements=place_subject(metrics, rows, 6),
        rows=rows,
        venues=[],
        funnel=funnel,
        cohort_size=2,
        institutions=2,
    )
    assert "withheld" in path.read_text(encoding="utf-8")


def test_the_guardrail_stops_a_report_that_names_a_cohort_member(tmp_path, config_dict):
    """The check runs on the finished file, not on good intentions."""
    config_dict["subfield"]["label"] = "work with A5023888391"
    with pytest.raises(GuardrailViolation):
        written_report(tmp_path, config_dict)


def test_no_em_dashes_in_the_report(tmp_path, config_dict):
    assert "—" not in written_report(tmp_path, config_dict).read_text(encoding="utf-8")


def test_the_venue_list_leaves_out_preprints_and_meeting_abstracts():
    """Counting every record on a profile put arXiv and SSRN at the top of this
    table, which describes where the subfield deposits, not where it publishes."""
    from tenuretrack.metrics import window_papers

    preprint = parse_work(
        {
            "id": "https://openalex.org/Wpre",
            "doi": "https://doi.org/10.1/pre",
            "publication_year": 2020,
            "type": "preprint",
            "primary_location": {
                "source": {
                    "id": "https://openalex.org/S9",
                    "display_name": "arXiv",
                    "type": "repository",
                }
            },
            "authorships": [],
        }
    )
    journal = paper(source="S1", name="Chem Mater")

    kept = window_papers([preprint, journal], 2020, 6, ["article"])
    assert [w.source_name for w in kept] == ["Chem Mater"]

    listed = [name for name, *_ in top_venues(kept, {"S1": 9.0}, 5.0)]
    assert listed == ["Chem Mater"]
    assert "arXiv" not in listed


def test_a_window_still_running_is_flagged(tmp_path, config_dict):
    """A subject whose final career year is the current calendar year has had
    part of a year where every cohort member had all of it."""
    text = written_report(
        tmp_path, config_dict, horizon=6, career_year=6, final_year_incomplete=True
    ).read_text(encoding="utf-8")
    assert "still running" in text
    assert "partial year short" in text


def test_a_finished_window_is_not_flagged(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "still running" not in text


# ------------------------------------------------------- a stopped clock


def test_a_stopped_clock_moves_the_comparison_year_back(config_dict):
    """Reading someone at their calendar year would compare them against people
    who had uninterrupted time, which is what an extension exists to prevent."""
    import datetime as _dt

    config_dict["subject"]["start_year"] = 2021
    config_dict["subject"]["clock_extension_years"] = 1
    config = build_config(config_dict)
    today = _dt.date(2026, 8, 28)

    assert config.subject.current_career_year(today) == 6
    assert config.subject.clock_year(today) == 5
    assert comparison_horizon(config.subject.clock_year(today), 6) == 5


def test_no_extension_leaves_the_clock_where_it_was(config_dict):
    import datetime as _dt

    config_dict["subject"]["start_year"] = 2021
    config = build_config(config_dict)
    today = _dt.date(2026, 8, 28)
    assert config.subject.clock_year(today) == config.subject.current_career_year(today)


def test_a_clock_year_never_drops_below_one(config_dict):
    import datetime as _dt

    config_dict["subject"]["start_year"] = 2026
    config_dict["subject"]["clock_extension_years"] = 3
    subject = build_config(config_dict).subject
    assert subject.clock_year(_dt.date(2026, 8, 28)) == 1


def test_the_report_explains_the_stopped_clock(tmp_path, config_dict):
    config_dict["subject"]["start_year"] = 2021
    config_dict["subject"]["clock_extension_years"] = 1
    text = written_report(
        tmp_path, config_dict, horizon=5, career_year=6, extension=1
    ).read_text(encoding="utf-8")
    assert "clock was stopped for 1 year" in text
    assert "year 5 of the tenure clock" in text
    assert "2021 to 2026" in text
    assert "grants time rather than removing the work" in text


def test_the_report_states_an_era_gap_it_could_not_close(tmp_path, config_dict):
    """Nobody who started with the subject has finished the horizon yet."""
    config_dict["subject"]["start_year"] = 2022
    config_dict["cohort"]["start_window"] = [2010, 2020]
    text = written_report(
        tmp_path, config_dict, horizon=4, career_year=5
    ).read_text(encoding="utf-8")
    assert "began at least 2 year(s) before" in text
    assert "Publishing conventions move" in text


def test_a_cohort_overlapping_the_subject_gets_no_era_note(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "Publishing conventions move" not in text


def test_a_report_with_no_extension_says_nothing_about_one(tmp_path, config_dict):
    assert "clock was stopped" not in written_report(
        tmp_path, config_dict
    ).read_text(encoding="utf-8")


def test_the_chaperone_finding_lands_under_the_venue_table(tmp_path, config_dict):
    """Where it changes a reading, not in a footer nobody reaches.

    A list of top-quartile journals invites the inference that a paper in one
    came out of the author's own group. The sentence saying how often it did
    belongs against that list.
    """
    text = written_report(
        tmp_path, config_dict,
        chaperone=["Across every paper the cohort wrote, it went better.",
                   "Comparing the same 770 people against themselves, and so on."],
    ).read_text(encoding="utf-8")
    assert "Who led the papers that reached those venues" in text
    assert text.index("| Venue |") < text.index("Who led the papers")
    assert text.index("Who led the papers") < text.index("How the cohort was built")
    assert "10.1073/pnas.1800471115" in text
    # The footer pointer is the fallback for a run without the pass, and would
    # be a second, weaker mention of something the body now carries.
    assert "asks a second question" not in text


def test_without_the_pass_the_report_still_points_at_it(tmp_path, config_dict):
    text = written_report(tmp_path, config_dict).read_text(encoding="utf-8")
    assert "Who led the papers that reached those venues" not in text
    assert "asks a second question" in text
