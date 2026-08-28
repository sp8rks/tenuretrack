"""Shared fixtures. Everything here is synthetic; no real OpenAlex data."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tenuretrack.openalex import MAILTO_ENV_VAR


@pytest.fixture(autouse=True)
def _no_ambient_mailto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer's own OPENALEX_MAILTO change a test outcome."""
    monkeypatch.delenv(MAILTO_ENV_VAR, raising=False)


VALID_CONFIG: dict[str, Any] = {
    "subject": {
        "name": "Jane Doe",
        "orcid": "0000-0002-1825-0097",
        "openalex_author_ids": [],
        "institution_ror": "https://ror.org/03r0ha626",
        "institution_name": "University of X",
        "start_year": 2015,
        "clock_notes": "",
    },
    "subfield": {
        "label": "example subfield",
        "topics": [
            {"id": "T10001", "name": "Topic A"},
            {"id": "T10002", "name": "Topic B"},
        ],
        "excluded_topics": [],
    },
    "cohort": {
        "start_window": [2008, 2018],
        "horizon_years": 6,
        "countries": ["US"],
        "institution_types": ["education"],
        "core_topic_share_min": 0.25,
        "min_led_papers": 3,
        "min_cell_size": 5,
        "bootstrap_iterations": 2000,
        "article_types": ["article"],
    },
    "output": {"dir": "results", "slides": True, "chaperone": True},
}


@pytest.fixture
def config_dict() -> dict[str, Any]:
    """A fresh, valid config mapping that a test can mutate freely."""
    return copy.deepcopy(VALID_CONFIG)
