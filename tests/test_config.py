"""Validation of the `benchmark.yaml` subject spec."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tenuretrack.config import ConfigError, build_config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def problems_from(data: dict) -> str:
    with pytest.raises(ConfigError) as excinfo:
        build_config(data)
    return "\n".join(excinfo.value.problems)


def test_valid_config_round_trips(config_dict):
    config = build_config(config_dict)
    assert config.subject.name == "Jane Doe"
    assert config.subject.orcid == "0000-0002-1825-0097"
    assert config.subfield.topic_ids == ("T10001", "T10002")
    assert config.cohort.start_window == (2008, 2018)
    assert config.cohort.horizons == (1, 2, 3, 4, 5, 6)
    assert config.output.dir == Path("results")
    assert config.is_runnable


def test_career_year_counts_from_one(config_dict):
    subject = build_config(config_dict).subject
    assert subject.career_year(2015) == 1
    assert subject.career_year(2020) == 6


def test_ror_and_country_are_normalized(config_dict):
    config_dict["subject"]["institution_ror"] = "03r0ha626"
    config_dict["cohort"]["countries"] = ["us"]
    config = build_config(config_dict)
    assert config.subject.institution_ror == "https://ror.org/03r0ha626"
    assert config.cohort.countries == ("US",)


def test_author_ids_are_shortened(config_dict):
    config_dict["subject"]["openalex_author_ids"] = ["https://openalex.org/A5023888391"]
    config = build_config(config_dict)
    assert config.subject.openalex_author_ids == ("A5023888391",)


def test_orcid_url_form_is_accepted(config_dict):
    config_dict["subject"]["orcid"] = "https://orcid.org/0000-0002-1825-0097"
    assert build_config(config_dict).subject.orcid == "0000-0002-1825-0097"


def test_placeholder_orcid_is_allowed_but_not_runnable(config_dict):
    config_dict["subject"]["orcid"] = "FILL_ME"
    config = build_config(config_dict)
    assert config.subject.orcid is None
    assert not config.is_runnable
    with pytest.raises(ConfigError, match="tenuretrack init"):
        config.require_runnable()


def test_empty_topics_are_allowed_but_not_runnable(config_dict):
    config_dict["subfield"]["topics"] = []
    config = build_config(config_dict)
    assert not config.is_runnable
    assert any("subfield.topics is empty" in p for p in config.unresolved())


def test_author_ids_alone_make_the_subject_resolved(config_dict):
    config_dict["subject"]["orcid"] = "FILL_ME"
    config_dict["subject"]["openalex_author_ids"] = ["A5023888391"]
    assert build_config(config_dict).is_runnable


def test_missing_section_is_reported(config_dict):
    del config_dict["cohort"]
    assert "missing required section: cohort" in problems_from(config_dict)


def test_unknown_key_is_reported(config_dict):
    config_dict["cohort"]["start_windows"] = [2008, 2018]
    assert "unknown key(s) at cohort: start_windows" in problems_from(config_dict)


def test_every_problem_is_reported_at_once(config_dict):
    config_dict["subject"]["start_year"] = 1800
    config_dict["cohort"]["core_topic_share_min"] = 25
    config_dict["subfield"]["topics"] = [{"id": "not-a-topic"}]
    with pytest.raises(ConfigError) as excinfo:
        build_config(config_dict)
    assert len(excinfo.value.problems) == 3


def test_bad_orcid_is_rejected(config_dict):
    config_dict["subject"]["orcid"] = "0000-0002-1825"
    assert "not a valid ORCID" in problems_from(config_dict)


def test_bad_ror_is_rejected(config_dict):
    config_dict["subject"]["institution_ror"] = "University of Utah"
    assert "not a valid ROR" in problems_from(config_dict)


def test_backwards_start_window_is_rejected(config_dict):
    config_dict["cohort"]["start_window"] = [2018, 2008]
    assert "backwards" in problems_from(config_dict)


def test_share_given_as_a_percent_is_rejected(config_dict):
    config_dict["cohort"]["core_topic_share_min"] = 25
    assert "share, not a percent" in problems_from(config_dict)


def test_min_cell_size_below_the_privacy_floor_is_rejected(config_dict):
    config_dict["cohort"]["min_cell_size"] = 3
    assert "re-identify" in problems_from(config_dict)


def test_duplicate_topic_is_rejected(config_dict):
    config_dict["subfield"]["topics"].append({"id": "T10001", "name": "Topic A again"})
    assert "more than once" in problems_from(config_dict)


def test_topic_in_both_lists_is_rejected(config_dict):
    config_dict["subfield"]["excluded_topics"] = [{"id": "T10001"}]
    assert "both topics and excluded_topics" in problems_from(config_dict)


def test_too_many_topics_is_rejected(config_dict):
    config_dict["subfield"]["topics"] = [
        {"id": f"T1000{n}", "name": f"Topic {n}"} for n in range(7)
    ]
    assert "working range is 4 to 6" in problems_from(config_dict)


def test_boolean_is_not_an_integer_year(config_dict):
    config_dict["subject"]["start_year"] = True
    assert "must be an integer year" in problems_from(config_dict)


def test_missing_file_names_the_path(tmp_path):
    with pytest.raises(ConfigError, match="no such config file"):
        load_config(tmp_path / "absent.yaml")


def test_unparseable_yaml_is_reported(tmp_path):
    path = tmp_path / "benchmark.yaml"
    path.write_text("subject: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="could not parse YAML"):
        load_config(path)


def test_load_config_records_its_source(tmp_path, config_dict):
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump(config_dict), encoding="utf-8")
    assert load_config(path).source == path


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / "benchmark.example.yaml",
        REPO_ROOT / "examples" / "taylor-sparks" / "benchmark.yaml",
        REPO_ROOT / "examples" / "huiwen-ji" / "benchmark.yaml",
    ],
    ids=["example-template", "taylor-sparks", "huiwen-ji"],
)
def test_shipped_configs_load(path):
    """The template and both acceptance examples must always parse."""
    config = load_config(path)
    assert config.subject.institution_ror.startswith("https://ror.org/")
    assert config.cohort.min_cell_size >= 5
