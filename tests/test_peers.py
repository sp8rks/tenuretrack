"""Restricting a cohort to institutions of similar standing (peers.py).

Every institution and person here is invented. No test touches the network.
"""

from __future__ import annotations

import pytest

from tenuretrack.peers import (
    MIN_PEER_COHORT,
    enough_people,
    institution_ranking,
    peer_group,
)
from tenuretrack.pool import parse_candidate

SUBJECT_ROR = "03r0ha626"


def person(ident: str, *affiliations: tuple[str, str, str]):
    """One candidate with the affiliations given as (ror, name, type)."""
    return parse_candidate(
        {
            "id": f"https://openalex.org/{ident}",
            "display_name": f"Person {ident}",
            "works_count": 40,
            "cited_by_count": 400,
            "summary_stats": {"h_index": 10},
            "topics": [],
            "affiliations": [
                {
                    "institution": {
                        "ror": f"https://ror.org/{ror}",
                        "display_name": name,
                        "country_code": "US",
                        "type": kind,
                    },
                    "years": [2019],
                }
                for ror, name, kind in affiliations
            ],
        }
    )


def cohort_of(counts: dict[str, int]):
    """`counts` maps a ror to how many people sit at it."""
    out = []
    n = 0
    for ror, people in counts.items():
        for _ in range(people):
            n += 1
            out.append(person(f"A{n:07d}", (ror, f"University of {ror}", "education")))
    return out


# --------------------------------------------------------------- the ordering


def test_institutions_rank_by_how_many_on_topic_people_they_carry():
    ranking = institution_ranking(cohort_of({"aaa": 5, "bbb": 9, "ccc": 1}))
    assert [r.ror for r in ranking] == ["bbb", "aaa", "ccc"]
    assert [r.people for r in ranking] == [9, 5, 1]


def test_a_person_counts_once_even_with_a_joint_appointment():
    """A national-lab joint appointment should not vote twice.

    Only the first qualifying affiliation counts, which is the one OpenAlex
    treats as primary.
    """
    people = [
        person("A0000001", ("aaa", "A Uni", "education"), ("bbb", "B Uni", "education"))
    ]
    ranking = institution_ranking(people)
    assert [(r.ror, r.people) for r in ranking] == [("aaa", 1)]


def test_a_non_university_affiliation_is_skipped():
    people = [
        person("A0000001", ("lab", "Some Lab", "facility"), ("aaa", "A Uni", "education"))
    ]
    ranking = institution_ranking(people)
    assert [r.ror for r in ranking] == ["aaa"]


# ------------------------------------------------------------- the peer group


def test_the_window_is_centred_on_the_subject():
    ranking = institution_ranking(
        cohort_of({f"i{n:02d}": 100 - n for n in range(20)})
    )
    # The subject sits at i10, so a group of five is i08 through i12.
    group = peer_group(ranking, "i10", 5)
    assert group.subject_rank == 11
    assert group.total_institutions == 20
    assert sorted(group.rors) == ["i08", "i09", "i10", "i11", "i12"]


def test_a_subject_at_the_top_gets_a_full_group_below_them():
    """Near an end the window slides rather than shrinks.

    Halving the peer group for the highest-output subject in the field would
    give them the least reliable comparison of anyone.
    """
    ranking = institution_ranking(cohort_of({f"i{n:02d}": 100 - n for n in range(20)}))
    group = peer_group(ranking, "i00", 5)
    assert group.subject_rank == 1
    assert len(group.rors) == 5
    assert sorted(group.rors) == ["i00", "i01", "i02", "i03", "i04"]


def test_a_subject_at_the_bottom_gets_a_full_group_above_them():
    ranking = institution_ranking(cohort_of({f"i{n:02d}": 100 - n for n in range(20)}))
    group = peer_group(ranking, "i19", 5)
    assert len(group.rors) == 5
    assert sorted(group.rors) == ["i15", "i16", "i17", "i18", "i19"]


def test_a_group_wider_than_the_field_keeps_everyone():
    ranking = institution_ranking(cohort_of({"aaa": 3, "bbb": 2}))
    group = peer_group(ranking, "aaa", 50)
    assert sorted(group.rors) == ["aaa", "bbb"]


def test_an_institution_with_no_on_topic_people_has_no_rank():
    """The subject's own school may carry nobody else in the subfield.

    There is then no place in the ordering to centre on, so the group is the
    top of the field and the rank is reported as unknown rather than invented.
    """
    ranking = institution_ranking(cohort_of({"aaa": 3, "bbb": 2}))
    group = peer_group(ranking, "zzz", 1)
    assert group.subject_rank is None
    assert "zzz" in group.rors
    assert "aaa" in group.rors


def test_the_subject_institution_is_always_in_its_own_peer_group():
    ranking = institution_ranking(cohort_of({f"i{n:02d}": 100 - n for n in range(20)}))
    group = peer_group(ranking, "i19", 3)
    assert "i19" in group.rors


def test_a_full_ror_url_and_a_bare_id_mean_the_same_institution():
    ranking = institution_ranking(cohort_of({SUBJECT_ROR: 4, "bbb": 2}))
    group = peer_group(ranking, f"https://ror.org/{SUBJECT_ROR}", 1)
    assert group.subject_rank == 1


def test_a_peer_group_size_of_zero_is_a_programming_error():
    """Zero means "do not narrow" and is handled by the caller, not here."""
    with pytest.raises(ValueError):
        peer_group((), "aaa", 0)


# ----------------------------------------------------- the thinness guardrail


def test_a_thin_peer_cohort_is_called_out():
    warning = enough_people(26)
    assert warning is not None
    assert "26 people" in warning
    assert "peer_group_size" in warning


def test_a_large_enough_cohort_says_nothing():
    assert enough_people(MIN_PEER_COHORT) is None
    assert enough_people(MIN_PEER_COHORT + 1) is None


# ------------------------------------------------- the funnel step end to end


def test_the_screen_narrows_to_peers_and_records_a_funnel_step(config_dict):
    """The whole point, checked through the real screen rather than the parts."""
    from tenuretrack.config import build_config
    from tenuretrack.pool import Funnel, screen_pool

    config_dict["subfield"]["topics"] = [{"id": "T10001"}]
    config_dict["subject"]["institution_ror"] = f"https://ror.org/{SUBJECT_ROR}"
    config_dict["cohort"].update(
        {"peer_group_size": 2, "core_topic_share_min": 0.0, "countries": ["US"]}
    )
    config = build_config(config_dict)

    # Three institutions, the subject's in the middle by output.
    people = cohort_of({"big": 4, SUBJECT_ROR: 3, "small": 1})
    funnel = Funnel()
    kept = screen_pool(people, config, funnel)

    labels = [step.label for step in funnel.steps]
    assert "peer institutions" in labels

    rors = {a.ror for person in kept for a in person.affiliations}
    assert "small" not in rors, "the distant institution should be dropped"
    assert SUBJECT_ROR in rors and "big" in rors
    assert len(kept) == 7


def test_no_peer_step_when_the_feature_is_off(config_dict):
    from tenuretrack.config import build_config
    from tenuretrack.pool import Funnel, screen_pool

    config_dict["subfield"]["topics"] = [{"id": "T10001"}]
    config_dict["cohort"].update({"core_topic_share_min": 0.0, "countries": ["US"]})
    config = build_config(config_dict)
    assert config.cohort.peer_group_size == 0

    funnel = Funnel()
    kept = screen_pool(cohort_of({"big": 4, "small": 1}), config, funnel)
    assert "peer institutions" not in [s.label for s in funnel.steps]
    assert len(kept) == 5
