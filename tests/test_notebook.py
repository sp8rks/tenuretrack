"""The Colab notebook's glue: mailto, topic selection, and the download bundle."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from tenuretrack.config import load_config
from tenuretrack.guardrail import GuardrailViolation
from tenuretrack.notebook import (
    NotebookError,
    describe_config,
    keep_topics,
    list_results,
    numbered_topics,
    parse_selection,
    set_mailto,
    zip_results,
)
from tenuretrack.openalex import MAILTO_ENV_VAR, MailtoNotConfigured

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO_ROOT / "notebooks" / "tenuretrack_colab.ipynb"


@pytest.fixture
def config_file(tmp_path, config_dict) -> Path:
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump(config_dict, sort_keys=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------- mailto


def test_set_mailto_puts_the_address_in_the_environment():
    env: dict[str, str] = {}
    assert set_mailto("  jane@university.edu  ", env) == "jane@university.edu"
    assert env[MAILTO_ENV_VAR] == "jane@university.edu"


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "jane@university"])
def test_set_mailto_rejects_anything_that_is_not_an_address(bad):
    with pytest.raises(MailtoNotConfigured):
        set_mailto(bad, {})


PLACEHOLDER_ADDRESSES = {"you@university.edu"}


def test_no_email_address_is_hardcoded_in_the_notebook_or_the_glue():
    """CLAUDE.md rule 4: the address comes from the user, never from the repo."""
    import re

    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    sources = [
        (REPO_ROOT / "src" / "tenuretrack" / "notebook.py").read_text(encoding="utf-8"),
        NOTEBOOK.read_text(encoding="utf-8"),
    ]
    for text in sources:
        for found in email_re.findall(text):
            assert found in PLACEHOLDER_ADDRESSES, f"hardcoded address: {found}"


# ------------------------------------------------------------------ selection


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("1, 2, 4", [1, 2, 4]),
        ("1 2 4", [1, 2, 4]),
        ("2-4", [2, 3, 4]),
        ("4-2", [2, 3, 4]),
        ("all", [1, 2, 3, 4]),
        ("", [1, 2, 3, 4]),
        ("3, 3, 1", [1, 3]),
    ],
)
def test_parse_selection_accepts_how_people_actually_type(typed, expected):
    assert parse_selection(typed, 4) == expected


@pytest.mark.parametrize("typed", ["9", "0", "banana", "1-9"])
def test_parse_selection_explains_bad_input_without_a_traceback(typed):
    with pytest.raises(NotebookError) as excinfo:
        parse_selection(typed, 4)
    assert "1 to 4" in str(excinfo.value)


# ------------------------------------------------------------------- describe


def test_numbered_topics_are_one_based(config_dict):
    from tenuretrack.config import build_config

    lines = numbered_topics(build_config(config_dict))
    assert lines[0].strip().startswith("1. T10001")
    assert lines[1].strip().startswith("2. T10002")


def test_describe_config_reads_like_a_sentence_not_a_yaml_dump(config_file):
    text = describe_config(config_file)
    assert "Subject: Jane Doe" in text
    assert "University of X" in text
    assert "career year" in text
    assert "T10001" in text


def test_describe_config_names_what_is_still_unsettled(config_file, config_dict):
    config_dict["subfield"]["topics"] = []
    config_file.write_text(yaml.safe_dump(config_dict, sort_keys=False), encoding="utf-8")
    text = describe_config(config_file)
    assert "Still to settle" in text
    assert "subfield.topics is empty" in text


def test_a_broken_config_is_a_notebook_error_not_a_traceback(tmp_path):
    path = tmp_path / "benchmark.yaml"
    path.write_text("subject: {}\n", encoding="utf-8")
    with pytest.raises(NotebookError):
        describe_config(path)


# ---------------------------------------------------------------- keep_topics


def test_keep_topics_rewrites_the_config_in_place(config_file):
    kept = keep_topics(config_file, "1")
    assert [t.id for t in kept] == ["T10001"]
    config = load_config(config_file)
    assert config.subfield.topic_ids == ("T10001",)
    assert config.is_runnable


def test_dropped_topics_move_to_excluded_with_a_reason(config_file):
    keep_topics(config_file, "1", note="not my subfield")
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    excluded = raw["subfield"]["excluded_topics"]
    assert [row["id"] for row in excluded] == ["T10002"]
    assert "not my subfield" in excluded[0]["name"]


def test_keep_topics_leaves_the_rest_of_the_config_alone(config_file):
    before = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    keep_topics(config_file, [1])
    after = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert after["subject"] == before["subject"]
    assert after["cohort"] == before["cohort"]
    assert after["output"] == before["output"]
    assert after["subfield"]["label"] == before["subfield"]["label"]


def test_keeping_everything_twice_does_not_duplicate_exclusions(config_file):
    keep_topics(config_file, "1")
    keep_topics(config_file, "1")
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert len(raw["subfield"]["excluded_topics"]) == 1


def test_keep_topics_refuses_an_out_of_range_number(config_file):
    with pytest.raises(NotebookError):
        keep_topics(config_file, [7])


# --------------------------------------------------------------------- output


def test_list_results_is_empty_before_a_run(tmp_path):
    assert list_results(tmp_path / "results") == []


def test_zip_results_bundles_the_directory(tmp_path):
    results = tmp_path / "results"
    (results / "figures").mkdir(parents=True)
    (results / "report.md").write_text("median papers through year 6: 11\n", encoding="utf-8")
    (results / "figures" / "papers.png").write_bytes(b"\x89PNG\r\n")

    bundle = zip_results(results, tmp_path / "tenuretrack-results.zip")
    with zipfile.ZipFile(bundle) as archive:
        assert sorted(archive.namelist()) == ["figures/papers.png", "report.md"]


def test_zip_results_says_so_when_there_is_nothing_to_download(tmp_path):
    with pytest.raises(NotebookError) as excinfo:
        zip_results(tmp_path / "results")
    assert "run the pipeline first" in str(excinfo.value)


def test_zip_results_refuses_to_bundle_a_leak(tmp_path):
    """Nothing leaves the machine until the guardrail has seen it."""
    results = tmp_path / "results"
    results.mkdir()
    (results / "report.md").write_text("cohort member A5023888391\n", encoding="utf-8")

    dest = tmp_path / "tenuretrack-results.zip"
    with pytest.raises(GuardrailViolation):
        zip_results(results, dest)
    assert not dest.exists()


# ------------------------------------------------------------------- notebook


def test_notebook_is_valid_and_has_no_saved_output():
    """A committed notebook with output would carry someone's data in git."""
    import json

    doc = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert doc["nbformat"] >= 4
    for cell in doc["cells"]:
        assert cell.get("outputs", []) == []
        assert cell.get("execution_count") is None


def test_notebook_prose_stays_descriptive():
    """CLAUDE.md rule 3, applied to the surface most faculty will actually read."""
    import json

    doc = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    prose = "\n".join(
        "".join(cell["source"]) for cell in doc["cells"] if cell["cell_type"] == "markdown"
    ).lower()
    for word in ("expected", "threshold", "target", "quota", "on track", "at risk"):
        assert word not in prose, f"notebook prose prescribes: {word}"
    assert "—" not in prose, "no em-dashes in prose"
