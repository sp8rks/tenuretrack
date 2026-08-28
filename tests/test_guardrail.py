"""The aggregates-only guardrail. Every name here is invented."""

from __future__ import annotations

from pathlib import Path

import pytest

from tenuretrack.guardrail import (
    PRESCRIPTIVE_TERMS,
    GuardrailError,
    GuardrailViolation,
    assert_aggregates_only,
    assert_directory_aggregates_only,
    scan_directory,
    scan_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

COHORT_NAMES = ["Ada Lovelace", "Grete Hermann", "Sofia Kovalevskaya"]
COHORT_IDS = ["A5023888391", "https://openalex.org/A5017761987"]

CLEAN_REPORT = """# Norms through year 6

| metric | p25 | median | p75 |
|---|---|---|---|
| publications | 9 | 14 | 21 |
| lead-author publications | 4 | 7 | 11 |

Cohort of 61 people across 34 institutions. Cells with fewer than the
minimum cell size are suppressed and shown as <5.
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def rules(violations) -> set[str]:
    return {v.rule for v in violations}


def test_a_clean_report_passes(tmp_path):
    path = write(tmp_path, "benchmarks.md", CLEAN_REPORT)
    assert_aggregates_only(path, COHORT_NAMES, COHORT_IDS)


def test_openalex_author_id_is_caught(tmp_path):
    path = write(tmp_path, "report.md", "Top contributor: A5099999999\n")
    violations = scan_file(path)
    assert rules(violations) == {"openalex_author_id"}
    assert violations[0].line == 1


def test_orcid_is_caught(tmp_path):
    path = write(tmp_path, "report.md", "orcid 0000-0002-1825-0097\n")
    assert "orcid" in rules(scan_file(path))


def test_orcid_ending_in_x_is_caught(tmp_path):
    path = write(tmp_path, "report.md", "0000-0002-1694-233X\n")
    assert "orcid" in rules(scan_file(path))


def test_cohort_name_is_caught(tmp_path):
    path = write(tmp_path, "report.md", "Line one\nSee also Ada Lovelace here.\n")
    violations = scan_file(path, COHORT_NAMES)
    assert rules(violations) == {"cohort_name"}
    assert violations[0].line == 2


def test_name_matching_ignores_case_and_accents(tmp_path):
    path = write(tmp_path, "report.md", "grete hermann\n")
    assert "cohort_name" in rules(scan_file(path, ["Grete Hermänn"]))


def test_name_matching_needs_a_whole_word(tmp_path):
    path = write(tmp_path, "report.md", "The Adam Lovelacey Prize\n")
    assert scan_file(path, ["Ada Lovelace"]) == []


def test_a_violation_never_repeats_the_name_it_caught(tmp_path):
    """A guardrail failure is printed in CI logs; it must not leak the name."""
    path = write(tmp_path, "report.md", "Ada Lovelace, A5023888391, 0000-0002-1825-0097\n")
    with pytest.raises(GuardrailViolation) as excinfo:
        assert_aggregates_only(path, COHORT_NAMES, COHORT_IDS)
    message = str(excinfo.value)
    assert "Ada Lovelace" not in message
    assert "A5023888391" not in message
    assert "0000-0002-1825-0097" not in message


def test_cohort_id_in_url_form_is_caught(tmp_path):
    path = write(tmp_path, "report.md", "see A5017761987\n")
    assert {"openalex_author_id", "cohort_id"} <= rules(scan_file(path, [], COHORT_IDS))


@pytest.mark.parametrize("term", PRESCRIPTIVE_TERMS)
def test_every_prescriptive_word_is_caught(tmp_path, term):
    path = write(tmp_path, "report.md", f"The {term} for this year.\n")
    violations = scan_file(path)
    assert "prescriptive_wording" in rules(violations)


def test_plural_prescriptive_words_are_caught(tmp_path):
    path = write(tmp_path, "report.md", "Departmental thresholds and targets.\n")
    assert len([v for v in scan_file(path) if v.rule == "prescriptive_wording"]) == 2


def test_minimum_cell_size_is_the_one_allowed_use_of_minimum(tmp_path):
    path = write(tmp_path, "report.md", "Cells below the minimum cell size are hidden.\n")
    assert scan_file(path) == []


def test_bare_minimum_is_still_caught(tmp_path):
    path = write(tmp_path, "report.md", "The minimum for promotion.\n")
    assert "prescriptive_wording" in rules(scan_file(path))


def test_words_that_merely_contain_a_forbidden_word_are_fine(tmp_path):
    path = write(
        tmp_path,
        "report.md",
        "Embargoed barrier data, targeted sampling, requirements of the method.\n",
    )
    assert scan_file(path) == []


def test_a_csv_with_one_row_per_person_is_caught(tmp_path):
    rows = "\n".join(f"{n},7,3" for n in range(3))
    path = write(tmp_path, "cohort.csv", f"member,pubs,led\n{rows}\n")
    violations = scan_file(path, cohort_size=3)
    assert rules(violations) == {"per_person_table"}


def test_an_aggregate_csv_of_a_different_shape_passes(tmp_path):
    path = write(
        tmp_path,
        "benchmarks.csv",
        "horizon,metric,p25,p50,p75\n1,pubs,0,1,2\n2,pubs,1,3,5\n",
    )
    assert scan_file(path, cohort_size=61) == []


def test_the_row_count_rule_needs_a_known_cohort_size(tmp_path):
    path = write(tmp_path, "benchmarks.csv", "a,b\n1,2\n")
    assert scan_file(path) == []


def test_a_directory_scan_finds_the_one_bad_file(tmp_path):
    write(tmp_path, "good.md", CLEAN_REPORT)
    write(tmp_path, "bad.md", "Ada Lovelace\n")
    violations = scan_directory(tmp_path, COHORT_NAMES)
    assert len(violations) == 1
    assert violations[0].path.name == "bad.md"


def test_a_missing_results_directory_is_not_a_violation(tmp_path):
    assert scan_directory(tmp_path / "results") == []


def test_assert_directory_raises_on_the_first_bad_file(tmp_path):
    write(tmp_path, "bad.md", "A5099999999\n")
    with pytest.raises(GuardrailViolation):
        assert_directory_aggregates_only(tmp_path)


def test_scanning_a_missing_file_is_an_error(tmp_path):
    with pytest.raises(GuardrailError):
        scan_file(tmp_path / "absent.md")


def test_images_are_skipped_rather_than_decoded(tmp_path):
    path = tmp_path / "figure.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert scan_file(path, COHORT_NAMES) == []


def test_a_deck_is_scanned_for_names(tmp_path):
    pptx = pytest.importorskip("pptx")
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Cohort: Ada Lovelace"
    path = tmp_path / "deck.pptx"
    presentation.save(str(path))
    assert "cohort_name" in rules(scan_file(path, COHORT_NAMES))


def test_a_clean_deck_passes(tmp_path):
    pptx = pytest.importorskip("pptx")
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Publications through year 6"
    path = tmp_path / "deck.pptx"
    presentation.save(str(path))
    assert scan_file(path, COHORT_NAMES) == []


@pytest.mark.parametrize(
    "results_dir",
    sorted((REPO_ROOT / "examples").glob("*/results")),
    ids=lambda p: p.parent.name,
)
def test_committed_example_results_are_aggregates_only(results_dir):
    """Runs on every committed example results directory, on every CI run."""
    assert_directory_aggregates_only(results_dir)
