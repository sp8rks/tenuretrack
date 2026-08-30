"""The Colab notebook's glue: mailto, topic selection, and the download bundle."""

from __future__ import annotations

import re
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
    run_cli,
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
    # NotebookError for the cases a notebook reader can act on, the client's
    # own MailtoNotConfigured for the rest. Both refuse; the difference is who
    # the message is written for.
    with pytest.raises((NotebookError, MailtoNotConfigured)):
        set_mailto(bad, {})


def test_an_empty_email_points_at_the_box_not_at_a_shell():
    """The client's message says to `export OPENALEX_MAILTO`.

    That is the right instruction in a terminal and a baffling one in a
    notebook whose form has a box for it three lines above the failure.
    """
    with pytest.raises(NotebookError) as caught:
        set_mailto("", {})
    message = str(caught.value)
    assert "your_email" in message
    assert "export" not in message


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


# ------------------------------------------- run_cli (the silent-failure guard)


def test_run_cli_returns_what_the_command_printed():
    printed = []
    output = run_cli("--version", on_line=printed.append)
    assert "tenuretrack" in output
    assert printed  # the cell sees it live, not just at the end


def test_run_cli_raises_instead_of_letting_a_failure_pass():
    with pytest.raises(NotebookError) as caught:
        run_cli("init", on_line=lambda _line: None)
    message = str(caught.value)
    assert "`init` step did not finish" in message
    assert "exit code" in message


def test_run_cli_quotes_the_error_back_to_the_reader(tmp_path, monkeypatch):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    with pytest.raises(NotebookError, match="no such config file"):
        run_cli(
            "run",
            "--config",
            str(tmp_path / "absent.yaml"),
            on_line=lambda _line: None,
        )


def test_run_cli_reports_a_missing_executable():
    import tenuretrack.notebook as notebook

    def explode(*_args, **_kwargs):
        raise OSError("no such file")

    original = notebook.subprocess.Popen
    notebook.subprocess.Popen = explode
    try:
        with pytest.raises(NotebookError, match="could not start tenuretrack"):
            run_cli("--version")
    finally:
        notebook.subprocess.Popen = original


# ------------------------------------------------------------- the api key


def test_a_key_goes_into_the_environment():
    from tenuretrack.notebook import set_api_key
    from tenuretrack.openalex import API_KEY_ENV_VAR

    env = {}
    message = set_api_key("  my-key  ", env)
    assert env[API_KEY_ENV_VAR] == "my-key"
    assert "ten times" in message


def test_a_blank_key_is_allowed_and_says_what_it_costs():
    from tenuretrack.notebook import set_api_key
    from tenuretrack.openalex import API_KEY_ENV_VAR

    env = {API_KEY_ENV_VAR: "stale"}
    message = set_api_key("", env)
    assert API_KEY_ENV_VAR not in env
    assert "stop partway" in message
    assert "openalex.org/settings/api" in message


def notebook_source() -> str:
    import json

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return chr(10).join("".join(cell["source"]) for cell in nb["cells"])


def test_the_notebook_has_no_form_box_for_the_api_key():
    """Colab writes form values back into the .ipynb, so a key typed in a box is
    a key written to the user's Drive that travels with the shared notebook."""
    joined = notebook_source()
    assert "#@param" in joined, "the other fields are still forms"
    assert not re.search(r'api_key\s*=\s*""\s*#@param', joined)
    assert "prompt_for_api_key" in joined, "the key is asked for at run time"


def test_the_notebook_says_where_to_get_a_key_and_that_it_is_optional():
    joined = notebook_source()
    assert "openalex.org/settings/api" in joined
    assert "press Enter" in joined or "skip the key" in joined


SECRET_SHAPED = re.compile(
    r"\b(?=[A-Za-z0-9]{20,}\b)(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])"
    r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+\b"
)
"""Twenty or more characters, mixed case, at least one digit, no separators.

That is what an API key looks like and what ordinary prose and identifiers do
not: `appointment_start_year` has underscores, `OpenAlex` has no digits.
"""


def test_no_secret_shaped_string_is_committed_in_the_notebook():
    found = SECRET_SHAPED.search(notebook_source())
    assert not found, f"something key-shaped is committed: {found and found.group(0)[:6]}..."


def test_the_secret_scanner_would_actually_catch_a_key():
    """A guard nobody has seen fire is a guard nobody should trust."""
    assert SECRET_SHAPED.search("key = Xk3Qz9Rb2Tn7Vw4Ly8Ms1")  # invented, not a real key
    assert not SECRET_SHAPED.search("appointment_start_year = 2019")
    assert not SECRET_SHAPED.search("openalex.org/settings/api")


def test_the_notebook_asks_about_a_stopped_clock():
    """Parental leave, medical leave and pandemic extensions are ordinary, and a
    notebook user has no other way to say so."""
    joined = notebook_source()
    assert "years_the_clock_was_stopped = 0" in joined
    assert "--clock-extension" in joined
    assert "Leave it at 0 if" in joined


def notebook_prose() -> str:
    """Notebook source with line wrapping flattened.

    Markdown cells are hard-wrapped, so a sentence a test cares about is split
    across lines in the file and matches nothing verbatim.
    """
    return re.sub(r"\s+", " ", notebook_source())


def test_the_notebook_says_the_extension_stays_local():
    prose = notebook_prose()
    assert "not sent to OpenAlex" in prose
    assert "nothing about why the clock stopped is asked for or recorded" in prose


def test_the_notebook_explains_why_the_extension_matters():
    prose = notebook_prose()
    assert "compared against people at year five" in prose
    assert "does not un-write what you published" in prose


def test_every_code_cell_is_valid_python():
    """A cell that does not parse fails on the reader's first run, not on ours.

    The `\n` in a print call was flattened into a real newline by an editor
    round-trip, which split the string literal across two lines and made the
    details cell a SyntaxError. Nothing caught it, because the other tests read
    the notebook as text and text has no opinion about whether it parses. The
    notebook is the surface most people meet this tool through, so its cells
    are held to compiling.
    """
    import ast
    import json

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for index, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        # Colab shell escapes and magics are not Python and never reach the parser.
        stripped = "\n".join(
            line
            for line in source.splitlines()
            if not line.lstrip().startswith(("!", "%"))
        )
        try:
            ast.parse(stripped)
        except SyntaxError as exc:  # pragma: no cover - the message is the point
            pytest.fail(f"cell {index} does not parse: line {exc.lineno}, {exc.msg}")


# ------------------------------------------------------- peer institutions


def test_set_peer_group_records_the_size(config_file):
    from tenuretrack.notebook import set_peer_group

    line = set_peer_group(config_file, 50)
    assert load_config(config_file).cohort.peer_group_size == 50
    assert "50 schools closest" in line
    assert "not a prestige ranking" in line


def test_set_peer_group_zero_keeps_every_university(config_file):
    from tenuretrack.notebook import set_peer_group

    line = set_peer_group(config_file, 0)
    assert load_config(config_file).cohort.peer_group_size == 0
    assert "whole subfield" in line


def test_a_narrow_peer_group_says_so_when_it_is_chosen(config_file):
    """The cost of narrowing should land at the moment of choosing.

    Fifteen schools is the number people reach for, and it leaves a cohort in
    the tens. Saying so in the funnel an hour later is too late to act on.
    """
    from tenuretrack.notebook import set_peer_group

    line = set_peer_group(config_file, 15)
    assert "15 schools is narrow" in line
    assert "two people per institution" in line


def test_a_negative_peer_group_is_refused(config_file):
    from tenuretrack.notebook import set_peer_group

    with pytest.raises(NotebookError):
        set_peer_group(config_file, -1)


def test_the_notebook_asks_about_peer_schools_up_front():
    """The choice belongs in the details cell, not after the cohort is built."""
    joined = notebook_source()
    assert "only_schools_like_mine" in joined
    assert "how_many_schools" in joined
    assert "set_peer_group" in joined
    prose = notebook_prose()
    assert "15 is too few" in prose, "the notebook should say what 15 costs"


def test_the_notebook_stays_short():
    """Prose that nobody reads protects nobody.

    This is a length ceiling, not a target. It exists because every warning
    added here has been worth adding, and the sum of them stopped being read.
    If a new warning genuinely earns its place, cut an older one or raise this
    number deliberately.
    """
    import json

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    words = sum(
        len("".join(c["source"]).split())
        for c in nb["cells"]
        if c["cell_type"] == "markdown"
    )
    # 1679 before this was cut; 1009 after. The ceiling sits just above where
    # the prose actually landed, so adding a paragraph is a deliberate act.
    assert words < 1050, f"notebook prose is {words} words"


def test_the_install_cell_checks_every_name_the_notebook_imports():
    """The guard is only worth having if it lists what the cells actually use.

    A Colab notebook and the package it drives are two files that travel
    apart: a copy saved in Drive can be newer than what pip fetched from the
    main branch. The install cell checks for the names by hand, so a name
    added to a later cell and not to that list would go back to failing as an
    ImportError three cells down.
    """
    import ast
    import json
    import re

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    source = chr(10).join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
    )

    guarded = set(re.findall(r'"(\w+)",', source.split("NEEDED = (")[1].split(")")[0]))

    imported: set[str] = set()
    stripped = chr(10).join(
        line
        for line in source.splitlines()
        if not line.lstrip().startswith(("!", "%"))
    )
    for node in ast.walk(ast.parse(stripped)):
        if isinstance(node, ast.ImportFrom) and node.module == "tenuretrack.notebook":
            imported.update(alias.name for alias in node.names)

    assert imported, "the notebook should import from tenuretrack.notebook"
    assert imported <= guarded, (
        f"the install cell does not check for: {sorted(imported - guarded)}"
    )


def test_the_install_cell_names_exist_on_the_package():
    """A guard listing a name that was renamed would fail every run."""
    import json
    import re

    from tenuretrack import notebook as module

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    source = chr(10).join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
    )
    guarded = re.findall(r'"(\w+)",', source.split("NEEDED = (")[1].split(")")[0])

    missing = [name for name in guarded if not hasattr(module, name)]
    assert not missing, f"the install cell checks for names that do not exist: {missing}"


# --------------------------------------------------------- the details form


def test_check_details_names_every_empty_box_at_once():
    """Three empty boxes should cost one run, not three.

    Validating one field per run means a person with three blanks runs the
    cell three times and reads three different errors, when the cell could
    have told them everything the first time.
    """
    from tenuretrack.notebook import check_details

    with pytest.raises(NotebookError) as caught:
        check_details(email="", orcid="", university="", start_year=2019)
    message = str(caught.value)
    assert "your_email" in message
    assert "orcid" in message
    assert "university" in message


def test_check_details_accepts_a_filled_in_form():
    from tenuretrack.notebook import check_details

    line = check_details(
        email="jane@university.edu",
        orcid="0000-0002-1825-0097",
        university="University of X",
        start_year=2019,
    )
    assert "0000-0002-1825-0097" in line
    assert "University of X" in line


def test_check_details_takes_an_orcid_url_as_well_as_a_bare_id():
    """People copy the URL from their ORCID page, because that is what it shows."""
    from tenuretrack.notebook import check_details

    assert check_details(
        email="jane@university.edu",
        orcid="https://orcid.org/0000-0002-1825-0097",
        university="University of X",
        start_year=2019,
    )


def test_check_details_rejects_an_orcid_that_is_not_one():
    from tenuretrack.notebook import check_details

    with pytest.raises(NotebookError) as caught:
        check_details(
            email="jane@university.edu",
            orcid="1825-0097",
            university="University of X",
            start_year=2019,
        )
    assert "0000-0002-1825-0097" in str(caught.value), "show the shape wanted"


@pytest.mark.parametrize("year", [1600, 2400, "soon", None])
def test_check_details_rejects_an_implausible_start_year(year):
    from tenuretrack.notebook import check_details

    with pytest.raises(NotebookError):
        check_details(
            email="jane@university.edu",
            orcid="0000-0002-1825-0097",
            university="University of X",
            start_year=year,
        )


def test_the_details_cell_checks_the_form_before_anything_slow():
    """The check belongs before the key prompt and the network call."""
    joined = notebook_source()
    assert "check_details(" in joined
    assert joined.index("check_details(") < joined.index("run_cli(\"init\"")


# ------------------------------------------- rerunning in a used folder


def _config_for(path, orcid, name="Someone Else"):
    path.write_text(
        yaml.safe_dump({"subject": {"name": name, "orcid": orcid}}), encoding="utf-8"
    )


def test_plan_init_runs_when_there_is_no_config(tmp_path):
    from tenuretrack.notebook import plan_init

    run, note = plan_init(tmp_path / "benchmark.yaml", orcid="0000-0002-1825-0097")
    assert run is True
    assert "0000-0002-1825-0097" in note


def test_plan_init_skips_when_the_config_is_for_the_same_person(tmp_path):
    """Rerunning the cell should not silently discard the topic choices."""
    from tenuretrack.notebook import plan_init

    path = tmp_path / "benchmark.yaml"
    _config_for(path, "0000-0002-1825-0097")
    run, note = plan_init(path, orcid="0000-0002-1825-0097")
    assert run is False
    assert "step 4" in note


def test_plan_init_reruns_when_start_over_is_ticked(tmp_path):
    from tenuretrack.notebook import plan_init

    path = tmp_path / "benchmark.yaml"
    _config_for(path, "0000-0002-1825-0097")
    run, _note = plan_init(path, orcid="0000-0002-1825-0097", start_over=True)
    assert run is True


def test_plan_init_refuses_to_benchmark_the_wrong_person(tmp_path):
    """The failure this exists for is the silent one.

    Reusing a folder for a second subject would otherwise build a cohort for
    whoever the file already named, and produce a report that looks perfectly
    reasonable.
    """
    from tenuretrack.notebook import plan_init

    path = tmp_path / "benchmark.yaml"
    _config_for(path, "0000-0001-8020-7711", name="Someone Else")
    with pytest.raises(NotebookError) as caught:
        plan_init(path, orcid="0000-0001-8091-9428")
    message = str(caught.value)
    assert "Someone Else" in message
    assert "0000-0001-8020-7711" in message
    assert "0000-0001-8091-9428" in message
    assert "start_over" in message
    assert "folder_name" in message


def test_plan_init_takes_an_orcid_url(tmp_path):
    from tenuretrack.notebook import plan_init

    path = tmp_path / "benchmark.yaml"
    _config_for(path, "0000-0002-1825-0097")
    run, _ = plan_init(path, orcid="https://orcid.org/0000-0002-1825-0097")
    assert run is False, "the URL and the bare id are the same person"


def test_the_details_cell_asks_before_it_overwrites(tmp_path):
    joined = notebook_source()
    assert "plan_init(" in joined
    assert "if run_init:" in joined
    assert joined.index("plan_init(") < joined.index("prompt_for_api_key()")
