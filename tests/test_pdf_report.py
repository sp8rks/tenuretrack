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
    ("venue_impact_median", "Median venue impact", 4.91, 3.26, 4.17, 5.87, "yes"),
    ("top_quartile_share", "Share in top-quartile venues", 0.17, 0.09, 0.21, 0.36,
     "yes"),
]

CHAPERONE_ROWS = [
    ["pooled_rate", "led", 1044, 10566, 0.2538, "", ""],
    ["pooled_rate", "first_not_led", 885, 3998, 0.2231, "", ""],
    ["pooled_rate", "middle", 1063, 16488, 0.2814, "", ""],
    ["gap", "middle_minus_led", 1090, "", 0.0276, 0.0062, 0.0498],
    ["paired", "median_led_share", 770, "", 0.1818, "", ""],
    ["paired", "median_middle_share", 770, "", 0.2500, "", ""],
    ["venue", "Journal of Examples", "", 400, 0.44, "", ""],
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
    # Every career year, not only the horizon: the trajectory page is drawn
    # from the years the horizon table throws away.
    _write_csv(
        out / "benchmarks.csv",
        [
            "career_year", "metric", "people", "p25", "p50", "p75",
            "p25_ci_low", "p25_ci_high", "p50_ci_low", "p50_ci_high",
            "p75_ci_low", "p75_ci_high",
        ],
        [
            [
                year, m, 300,
                round(p25 * year / 6, 2), round(p50 * year / 6, 2),
                round(p75 * year / 6, 2),
                round(p25 * year / 6, 2), round(p25 * year / 6, 2),
                round(p50 * year / 6, 2), round(p50 * year / 6, 2),
                round(p75 * year / 6, 2), round(p75 * year / 6, 2),
            ]
            for year in range(1, 7)
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


def _pages(path: Path) -> int:
    """How many pages the PDF holds, without a PDF library to ask.

    `/Type /Pages` is the page tree's root node rather than a page, so it has
    to come back out of the count or every document reads one page too long.
    """
    raw = path.read_bytes()
    return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")


def test_a_pdf_is_written_with_a_page_for_each_section(results, config):
    path = build_pdf_report(results, config)
    assert path.name == PDF_FILENAME
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
    # Cover, subject, trajectory, norms, funnel, venues, caveats. No chaperone
    # page, because this fixture has no chaperone.csv.
    assert _pages(path) == 7


def test_the_chaperone_pass_earns_its_own_page(results, config):
    """The finding most likely to change how a record reads belongs in the PDF.

    It used to live only in chaperone.md, which is a file most people never
    open, so its presence in the forwarded document is worth a test.
    """
    without = _pages(build_pdf_report(results, config))
    _write_csv(
        results / "chaperone.csv",
        ["section", "key", "people", "papers", "value", "low", "high"],
        CHAPERONE_ROWS,
    )
    assert _pages(build_pdf_report(results, config)) == without + 1


def test_every_metric_reaches_the_norms_table(results, config):
    """A key typed by hand once dropped median venue impact from this page.

    The order and the labels come from metrics.METRICS now, so a metric added
    there cannot silently miss the report.
    """
    from tenuretrack.metrics import METRICS as ALL_METRICS
    from tenuretrack.pdf_report import METRIC_LABELS, METRIC_ORDER

    assert tuple(m.key for m in ALL_METRICS) == METRIC_ORDER
    assert all(METRIC_LABELS[m.key] == m.label for m in ALL_METRICS)


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
