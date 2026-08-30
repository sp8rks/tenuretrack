"""Reading the pipeline's own output files back off disk.

Split out of `slides.py` so that nothing which only needs the numbers has to
import python-pptx. The deck is one optional artifact at the end of a run;
before this split a missing python-pptx broke `import tenuretrack.cli`, so a
long resumable `run` died at the import line rather than at the deck.

Nothing here recomputes anything. Every value is read from the files the
pipeline wrote, which is what keeps the deck, the PDF and the report from
disagreeing.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from tenuretrack.chaperone import CHAPERONE_CSV
from tenuretrack.config import Config
from tenuretrack.metrics import BENCHMARKS_CSV
from tenuretrack.pool import FUNNEL_FILENAME
from tenuretrack.report import SUBJECT_CSV, VENUES_CSV, load_venues

__all__ = ["SlideData", "load_slide_data", "subject_slug"]


@dataclass
class SlideData:
    """Everything the deck shows, already read off disk."""

    config: Config
    funnel: list[tuple[str, str, int, int]] = field(default_factory=list)
    benchmarks: list[dict] = field(default_factory=list)
    subject: list[dict] = field(default_factory=list)
    venues: list[tuple[str, int, float | None, bool]] = field(default_factory=list)
    role_rates: list[tuple[str, float | None]] = field(default_factory=list)
    career_year: int = 1
    horizon: int = 6

    @property
    def cohort_size(self) -> int:
        for row in self.funnel[::-1]:
            return row[2]
        return 0


def subject_slug(name: str) -> str:
    """A filename from a person's name, with nothing surprising in it."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "subject"


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load_slide_data(results: str | Path, config: Config) -> SlideData:
    """Read the pipeline's own output files. Nothing here recomputes anything."""
    results = Path(results)
    data = SlideData(config=config)

    funnel_path = results / FUNNEL_FILENAME
    if funnel_path.exists():
        for row in csv.DictReader(funnel_path.read_text(encoding="utf-8").splitlines()):
            data.funnel.append(
                (row["label"], row["rule"], int(row["kept"]), int(row["dropped"]))
            )

    benchmarks_path = results / BENCHMARKS_CSV
    if benchmarks_path.exists():
        data.benchmarks = list(
            csv.DictReader(benchmarks_path.read_text(encoding="utf-8").splitlines())
        )

    subject_path = results / SUBJECT_CSV
    if subject_path.exists():
        data.subject = list(
            csv.DictReader(subject_path.read_text(encoding="utf-8").splitlines())
        )
        if data.subject:
            data.career_year = int(data.subject[0]["career_year"])
            data.horizon = int(data.subject[0]["compared_at"])

    # Reuses the report's own parser rather than a second one here: two
    # readers of one file is how a deck and a report start disagreeing.
    if (results / VENUES_CSV).exists():
        data.venues = load_venues(results)

    chaperone_path = results / CHAPERONE_CSV
    if chaperone_path.exists():
        labels = {
            "led": "Led",
            "first_not_led": "First, not leading",
            "middle": "Middle author",
        }
        for row in csv.DictReader(chaperone_path.read_text(encoding="utf-8").splitlines()):
            if row["section"] == "pooled_rate":
                data.role_rates.append(
                    (labels.get(row["key"], row["key"]), _float(row["value"]))
                )
    return data
