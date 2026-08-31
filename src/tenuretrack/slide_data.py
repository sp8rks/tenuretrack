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
    role_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    gap: tuple[float, float | None, float | None] | None = None
    paired: dict[str, float] = field(default_factory=dict)
    venue_led_share: dict[str, float] = field(default_factory=dict)
    career_year: int = 1
    horizon: int = 6

    @property
    def has_chaperone(self) -> bool:
        """Whether `tenuretrack run` was asked for the led-versus-co-authored pass."""
        return bool(self.role_rates)

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
        # Every section, not only the pooled rates. The PDF draws the paired
        # comparison and the interval on the gap beside them, and a reader who
        # sees one without the others gets the weaker half of the finding.
        for row in csv.DictReader(chaperone_path.read_text(encoding="utf-8").splitlines()):
            section, key = row["section"], row["key"]
            value = _float(row["value"])
            if section == "pooled_rate":
                data.role_rates.append((labels.get(key, key), value))
                data.role_counts[labels.get(key, key)] = (
                    int(row["people"] or 0),
                    int(row["papers"] or 0),
                )
            elif section == "gap" and value is not None:
                data.gap = (value, _float(row["low"]), _float(row["high"]))
            elif section == "paired" and value is not None:
                data.paired[key] = value
                data.paired.setdefault("people", float(row["people"] or 0))
            elif section == "venue" and value is not None:
                data.venue_led_share[key] = value
    return data
