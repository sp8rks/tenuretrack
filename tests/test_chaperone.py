"""The chaperone analysis (TASKS.md task 7).

Two readings of the same data, which can disagree, plus a sign test written by
hand. These tests mostly check the arithmetic is what the report claims it is,
and that the wording does not overstate a cross-sectional approximation of a
longitudinal result.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from tenuretrack.career import AFFILIATION_LED, HIGH, StartEstimate
from tenuretrack.chaperone import (
    MIN_PAPERS_PER_ROLE,
    Gap,
    PairedTest,
    PersonRoles,
    led_vs_middle_gap,
    paired_within_person,
    person_roles,
    pooled_rates,
    sign_test,
    venue_coauthored_share,
    write_chaperone_csv,
    write_chaperone_md,
)
from tenuretrack.config import build_config
from tenuretrack.guardrail import PRESCRIPTIVE_TERMS, GuardrailViolation
from tenuretrack.works import FIRST_NOT_LED, LED, MIDDLE, parse_work

ME = "A1000001"
ARTICLES = ["article"]


def paper(year=2010, position="last", source="S1", name="Journal", who=ME):
    return parse_work(
        {
            "id": f"https://openalex.org/W{year}{position}{source}{who}",
            "doi": f"https://doi.org/10.1/{year}-{position}-{source}-{who}",
            "publication_year": year,
            "type": "article",
            "cited_by_count": 1,
            "primary_location": {
                "source": {
                    "id": f"https://openalex.org/{source}",
                    "display_name": name,
                    "type": "journal",
                }
            },
            "authorships": [
                {
                    "author": {"id": f"https://openalex.org/{who}"},
                    "author_position": position,
                    "is_corresponding": False,
                    "institutions": [],
                }
            ],
        }
    )


def roles(**kwargs):
    return PersonRoles(author_id=kwargs.pop("author_id", ME), **kwargs)


# ---------------------------------------------------------------- one person


def test_papers_are_split_by_role():
    works = [
        paper(2010, "last", "S10"),
        paper(2011, "middle", "S10"),
        paper(2012, "first", "S20"),
        paper(2013, "middle", "S20"),
    ]
    got = person_roles(
        works, ME, 2010, 6, ARTICLES, {"S10": 9.0, "S20": 1.0}, cutoff=5.0
    )
    assert got.led_papers == 1
    assert got.led_top == 1
    assert got.first_papers == 1
    assert got.first_top == 0
    assert got.middle_papers == 2
    assert got.middle_top == 1


def test_papers_with_an_unplaceable_venue_are_left_out_of_both_sides():
    """Otherwise the rate would track how well OpenAlex covers the venues a
    person happened to use, which differs by role."""
    works = [paper(2010, "last", "S30"), paper(2011, "last", "S40")]
    got = person_roles(works, ME, 2010, 6, ARTICLES, {"S30": 9.0}, cutoff=5.0)
    assert got.led_papers == 1


def test_no_cutoff_means_no_counts():
    works = [paper(2010, "last", "S1")]
    got = person_roles(works, ME, 2010, 6, ARTICLES, {"S1": 9.0}, cutoff=None)
    assert got.led_papers == 0


def test_a_persons_share_is_none_when_they_have_no_papers_in_that_role():
    assert roles(led_papers=0).share(LED) is None
    assert roles(led_papers=4, led_top=1).share(LED) == pytest.approx(0.25)


# ------------------------------------------------------------- pooled rates


def test_pooled_rates_count_papers_not_people():
    people = [
        roles(author_id="A1", led_papers=100, led_top=50),
        roles(author_id="A2", led_papers=1, led_top=0),
    ]
    by_role = {r.role: r for r in pooled_rates(people)}
    assert by_role[LED].papers == 101
    assert by_role[LED].rate == pytest.approx(50 / 101)
    assert by_role[LED].people == 2


def test_a_role_nobody_published_in_has_no_rate():
    by_role = {r.role: r for r in pooled_rates([roles(led_papers=3, led_top=1)])}
    assert by_role[MIDDLE].rate is None
    assert by_role[FIRST_NOT_LED].papers == 0


# ------------------------------------------------------------------- the gap


def test_the_gap_is_middle_minus_led():
    people = [roles(led_papers=10, led_top=2, middle_papers=10, middle_top=5)]
    gap = led_vs_middle_gap(people, iterations=200)
    assert gap.led_rate == pytest.approx(0.2)
    assert gap.middle_rate == pytest.approx(0.5)
    assert gap.gap == pytest.approx(0.3)


def test_the_gap_interval_brackets_the_estimate():
    rng = np.random.default_rng(5)
    people = [
        roles(author_id=f"A{i}", led_papers=8, led_top=2, middle_papers=8, middle_top=4)
        for i in range(60)
    ]
    gap = led_vs_middle_gap(people, iterations=400, rng=rng)
    assert gap.lo <= gap.gap <= gap.hi


def test_the_gap_is_reproducible():
    people = [
        roles(author_id=f"A{i}", led_papers=5, led_top=i % 3, middle_papers=5, middle_top=2)
        for i in range(40)
    ]
    first = led_vs_middle_gap(people, iterations=200, rng=np.random.default_rng(2))
    second = led_vs_middle_gap(people, iterations=200, rng=np.random.default_rng(2))
    assert first == second


def test_nobody_to_compare_gives_no_gap():
    assert led_vs_middle_gap([], iterations=100).gap is None


# ------------------------------------------------------------- the sign test


@pytest.mark.parametrize(
    ("higher", "lower", "expected"),
    [
        (0, 0, None),
        (5, 5, 1.0),
        (10, 0, 2 / 2**10),
        (0, 10, 2 / 2**10),
        (1, 1, 1.0),
    ],
)
def test_sign_test(higher, lower, expected):
    got = sign_test(higher, lower)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_the_sign_test_never_exceeds_one():
    assert sign_test(3, 3) <= 1.0
    assert sign_test(2, 3) <= 1.0


# --------------------------------------------------------- paired comparison


def test_only_people_with_papers_in_both_roles_are_paired():
    people = [
        roles(author_id="A1", led_papers=5, led_top=1, middle_papers=5, middle_top=3),
        roles(author_id="A2", led_papers=5, led_top=1),  # no middle papers
        roles(author_id="A3", middle_papers=5, middle_top=1),  # no led papers
    ]
    assert paired_within_person(people).people == 1


def test_someone_just_below_the_bar_is_excluded():
    thin = roles(
        led_papers=MIN_PAPERS_PER_ROLE - 1,
        led_top=1,
        middle_papers=10,
        middle_top=5,
    )
    assert paired_within_person([thin]).people == 0


def test_the_paired_test_counts_who_went_which_way():
    people = [
        roles(author_id="A1", led_papers=4, led_top=1, middle_papers=4, middle_top=3),
        roles(author_id="A2", led_papers=4, led_top=3, middle_papers=4, middle_top=1),
        roles(author_id="A3", led_papers=4, led_top=2, middle_papers=4, middle_top=2),
    ]
    got = paired_within_person(people)
    assert got.higher_on_middle == 1
    assert got.higher_on_led == 1
    assert got.ties == 1
    assert got.p_value == pytest.approx(1.0)


def test_a_consistent_effect_shows_a_small_p_value():
    people = [
        roles(author_id=f"A{i}", led_papers=5, led_top=1, middle_papers=5, middle_top=4)
        for i in range(12)
    ]
    got = paired_within_person(people)
    assert got.higher_on_middle == 12
    assert got.p_value < 0.001
    assert got.median_middle_share > got.median_led_share


def test_nobody_paired_is_reported_as_nobody():
    got = paired_within_person([])
    assert got == PairedTest(0, None, None, 0, 0, 0, None)


# ----------------------------------------------------------------- venues


def test_venue_shares_are_over_window_papers(config_dict):
    config = build_config(config_dict)
    works = {
        "A1": [
            paper(2010, "last", "S1", "Chem Mater", who="A1"),
            paper(2011, "middle", "S1", "Chem Mater", who="A1"),
            paper(2050, "last", "S1", "Chem Mater", who="A1"),  # outside the window
        ]
    }
    starts = {"A1": StartEstimate("A1", 2010, AFFILIATION_LED, HIGH)}
    got = venue_coauthored_share(works, starts, config)
    assert got[0] == ("Chem Mater", 2, pytest.approx(0.5))


def test_a_person_with_no_start_is_skipped(config_dict):
    works = {"A1": [paper(2010, "last", "S1", who="A1")]}
    assert venue_coauthored_share(works, {}, build_config(config_dict)) == []


# ----------------------------------------------------------------- the files


def sample():
    people = [
        roles(author_id=f"A{i}", led_papers=6, led_top=1, middle_papers=6, middle_top=3)
        for i in range(20)
    ]
    rates = pooled_rates(people)
    gap = led_vs_middle_gap(people, iterations=200, rng=np.random.default_rng(1))
    paired = paired_within_person(people)
    venues = [("Chemistry of Materials", 400, 0.35)]
    return rates, gap, paired, venues


def test_the_csv_holds_aggregates_only(tmp_path):
    rates, gap, paired, venues = sample()
    path = write_chaperone_csv(rates, gap, paired, venues, tmp_path / "c.csv")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    sections = {r["section"] for r in rows}
    assert sections == {"pooled_rate", "gap", "paired", "venue"}
    assert "A1000001" not in path.read_text(encoding="utf-8")


def test_the_report_credits_sekara_and_says_it_is_an_approximation(tmp_path, config_dict):
    rates, gap, paired, venues = sample()
    path = write_chaperone_md(
        rates, gap, paired, venues, tmp_path / "c.md",
        config=build_config(config_dict), cohort_size=20,
    )
    text = path.read_text(encoding="utf-8")
    assert "Sekara" in text
    assert "10.1073/pnas.1800471115" in text
    assert "not a replication" in text
    assert "should not be read against their figures" in text


def test_the_report_reads_as_description_not_instruction(tmp_path, config_dict):
    rates, gap, paired, venues = sample()
    path = write_chaperone_md(
        rates, gap, paired, venues, tmp_path / "c.md",
        config=build_config(config_dict), cohort_size=20,
    )
    text = path.read_text(encoding="utf-8").lower()
    for term in PRESCRIPTIVE_TERMS:
        assert term not in text, f"{term!r} turns a description into an instruction"


def test_the_report_says_both_readings_and_why(tmp_path, config_dict):
    rates, gap, paired, venues = sample()
    path = write_chaperone_md(
        rates, gap, paired, venues, tmp_path / "c.md",
        config=build_config(config_dict), cohort_size=20,
    )
    text = path.read_text(encoding="utf-8")
    assert "Across every paper the cohort wrote" in text
    assert "compared against themselves" in text
    assert "disagreement is the finding" in text
    assert "their own control" in text


def test_the_report_warns_about_missing_corresponding_flags(tmp_path, config_dict):
    rates, gap, paired, venues = sample()
    path = write_chaperone_md(
        rates, gap, paired, venues, tmp_path / "c.md",
        config=build_config(config_dict), cohort_size=20,
    )
    assert "Corresponding-author flags are missing" in path.read_text(encoding="utf-8")


def test_no_paired_people_is_stated_plainly(tmp_path, config_dict):
    path = write_chaperone_md(
        [], Gap(None, None, None, None, None, 0), PairedTest(0, None, None, 0, 0, 0, None),
        [], tmp_path / "c.md", config=build_config(config_dict), cohort_size=0,
    )
    text = path.read_text(encoding="utf-8")
    assert "no paired comparison" in text
    assert "Too few papers" in text


def test_the_guardrail_stops_a_chaperone_file_that_names_somebody(tmp_path, config_dict):
    rates, gap, paired, _ = sample()
    with pytest.raises(GuardrailViolation):
        write_chaperone_csv(
            rates, gap, paired, [("paper with A5023888391", 4, 0.5)], tmp_path / "c.csv"
        )


def test_no_em_dashes_in_the_chaperone_report(tmp_path, config_dict):
    rates, gap, paired, venues = sample()
    path = write_chaperone_md(
        rates, gap, paired, venues, tmp_path / "c.md",
        config=build_config(config_dict), cohort_size=20,
    )
    assert "—" not in path.read_text(encoding="utf-8")
