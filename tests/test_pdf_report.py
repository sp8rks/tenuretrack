"""The standalone PDF report (pdf_report.py).

No network, no LibreOffice. The fixtures are synthetic; the one name any of
these pages may carry is the subject's.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from tenuretrack.config import build_config
from tenuretrack.guardrail import PRESCRIPTIVE_TERMS, GuardrailViolation
from tenuretrack.pdf_report import PDF_FILENAME, build_pdf_report

MODULE = Path(__file__).resolve().parents[1] / "src" / "tenuretrack" / "pdf_report.py"

METRICS = [
    ("pubs", "Journal articles", 35, 14, 23, 38, "yes"),
    ("led", "Led articles (last or corresponding)", 17, 3, 6, 12, "yes"),
    ("citations", "Citations to those articles", 2593, 410, 942, 2128, "no"),
    ("h_index", "h-index over those articles", 22, 9, 14, 21, "yes"),
]


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def results(tmp_path) -> Path:
    """A results directory shaped like one `run` writes."""
    out = tmp_path / "results"
    _write_csv(
        out / "funnel.csv",
        ["step", "label", "rule", "kept", "dropped"],
        [
            [1, "candidates", "topics T10001", 8000, 0],
            [2, "core topic share", "at least 0.4", 2400, 5600],
            [3, "start in window", "between 2008 and 2018", 300, 2100],
        ],
    )
    _write_csv(
        out / "subject.csv",
        [
            "career_year", "compared_at", "metric", "label", "value",
            "cohort_p25", "cohort_p50", "cohort_p75", "position", "compared",
        ],
        [
            [14, 6, m, label, value, p25, p50, p75, "between", compared]
            for m, label, value, p25, p50, p75, compared in METRICS
        ],
    )
    _write_csv(
        out / "benchmarks.csv",
        [
            "career_year", "metric", "people", "p25", "p50", "p75",
            "p25_ci_low", "p25_ci_high", "p50_ci_low", "p50_ci_high",
            "p75_ci_low", "p75_ci_high",
        ],
        [
            [6, m, 300, p25, p50, p75, p25, p25, p50, p50, p75, p75]
            for m, _label, _v, p25, p50, p75, _c in METRICS
        ],
    )
    _write_csv(
        out / "venues.csv",
        ["venue", "cohort_papers", "impact", "top_quartile"],
        [
            ["Journal of Examples", 400, 7.5, "yes"],
            ["Letters of Examples", 120, 2.1, "no"],
        ],
    )
    return out


@pytest.fixture
def config(config_dict):
    config_dict["subfield"]["topics"] = [{"id": "T10001"}]
    return build_config(config_dict)


def test_a_pdf_is_written_with_a_page_for_each_section(results, config):
    path = build_pdf_report(results, config)
    assert path.name == PDF_FILENAME
    assert path.exists()

    raw = path.read_bytes()
    assert raw.startswith(b"%PDF")
    # Cover, subject, norms, funnel, venues, caveats.
    assert raw.count(b"/Type /Page\n") == 6 or raw.count(b"/Type /Page") >= 6


def test_the_pdf_needs_no_libreoffice(results, config, monkeypatch):
    """The whole reason this module exists.

    `slides.export_pdf` shells out to LibreOffice, which is not on a Colab
    machine. Emptying PATH would not stop a subprocess found by absolute path,
    so this asserts the stronger thing: nothing is spawned at all.
    """
    import subprocess

    def explode(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("the PDF report shelled out to something")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    assert build_pdf_report(results, config).exists()


def test_it_refuses_to_draw_from_an_unsafe_results_directory(results, config):
    """The PDF cannot be text-scanned, so its inputs are what get checked.

    matplotlib breaks a string into kerned glyph runs, so a substring scan of
    the PDF would miss a split name and report a safety it had not checked.
    The guarantee is that every page is drawn from files that were scanned.
    """
    leaky = results / "subject.csv"
    leaky.write_text(
        leaky.read_text(encoding="utf-8") + "\n# A5098498640\n", encoding="utf-8"
    )
    with pytest.raises(GuardrailViolation):
        build_pdf_report(results, config)
    assert not (results / PDF_FILENAME).exists()


def test_a_missing_optional_file_does_not_stop_the_pdf(results, config):
    """A run without a venue table still gets a report, minus that page."""
    (results / "venues.csv").unlink()
    assert build_pdf_report(results, config).exists()


def test_the_pdf_prose_stays_descriptive():
    """CLAUDE.md rule 3 applies to a generated document as much as a report."""
    prose = " ".join(
        re.findall(r'"((?:[^"\\]|\\.)*)"', MODULE.read_text(encoding="utf-8"))
    ).lower()
    pluralizable = {"threshold", "bar", "target", "quota"}
    for word in PRESCRIPTIVE_TERMS:
        body = r"\s+".join(re.escape(part) for part in word.split())
        if word in pluralizable:
            body += "s?"
        assert not re.search(rf"\b{body}\b", prose), (
            f"the PDF prose prescribes: {word}"
        )


def test_no_em_dashes_in_the_pdf_prose():
    assert chr(8212) not in MODULE.read_text(encoding="utf-8")


def test_numbers_are_written_the_way_a_reader_writes_them():
    from tenuretrack.pdf_report import _tidy

    assert _tidy(35.0) == "35"
    assert _tidy(0.49) == "0.49"
    assert _tidy(0.5) == "0.5"
    assert _tidy("") == ""
