"""The CLI surface. Task 1 registers the commands; the stages come later."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tenuretrack import __version__
from tenuretrack.cli import EXIT_BAD_CONFIG, EXIT_NOT_IMPLEMENTED, app
from tenuretrack.openalex import MAILTO_ENV_VAR

runner = CliRunner()

SUBCOMMANDS = ("init", "run", "chaperone", "slides", "show-cohort")


def text(result) -> str:
    """Everything the command printed, whichever stream it used."""
    out = result.output or ""
    try:
        err = result.stderr or ""
    except ValueError:  # click merged the streams already
        err = ""
    return out if err in out else out + err


def write_config(tmp_path, config_dict):
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump(config_dict), encoding="utf-8")
    return path


def test_version_is_printed():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_every_subcommand_is_registered(command):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert command in result.output


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_every_subcommand_has_help(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_missing_config_exits_with_the_path(tmp_path):
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "absent.yaml")])
    assert result.exit_code == EXIT_BAD_CONFIG
    assert "no such config file" in text(result)


def test_invalid_config_lists_the_problems(tmp_path, config_dict):
    config_dict["cohort"]["min_cell_size"] = 2
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_BAD_CONFIG
    assert "min_cell_size" in text(result)


def test_run_refuses_without_a_mailto(tmp_path, config_dict):
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_BAD_CONFIG
    assert MAILTO_ENV_VAR in text(result)


def test_init_refuses_without_a_mailto():
    result = runner.invoke(
        app,
        ["init", "--orcid", "0000-0002-1825-0097", "--institution", "X", "--start", "2021"],
    )
    assert result.exit_code == EXIT_BAD_CONFIG
    assert MAILTO_ENV_VAR in text(result)


def test_run_refuses_an_unresolved_config(monkeypatch, tmp_path, config_dict):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    config_dict["subfield"]["topics"] = []
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_BAD_CONFIG
    assert "subfield.topics is empty" in text(result)


def patch_pool(monkeypatch, outcome):
    """Point `run` at a fake client and a canned pool stage."""
    import tenuretrack.cli as cli

    monkeypatch.setattr(cli, "OpenAlexClient", lambda **_kwargs: FakeClient())

    def stage(_client, _config, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(cli, "build_pool", stage)


def fake_pool(kept=3):
    from tenuretrack.pool import Funnel, PoolResult

    funnel = Funnel()
    funnel.record("candidates", "topics", 100)
    funnel.record("university", "education", kept)
    return PoolResult(
        pool_size=100,
        kept=tuple(range(kept)),
        funnel=funnel,
        pool_path=Path("data/pool.jsonl.gz"),
        funnel_path=Path("results/funnel.csv"),
    )


def test_run_builds_the_pool_then_reports_what_is_not_built_yet(
    monkeypatch, tmp_path, config_dict
):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_pool(monkeypatch, fake_pool(kept=7))
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_NOT_IMPLEMENTED
    out = text(result)
    assert "7 candidates carried into career-start estimation" in out
    assert "not implemented yet" in out


def test_run_exits_separately_when_the_quota_runs_out(monkeypatch, tmp_path, config_dict):
    from tenuretrack.cli import EXIT_NETWORK
    from tenuretrack.openalex import QuotaExhausted

    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_pool(monkeypatch, QuotaExhausted("https://api.openalex.org/authors", 7200.0))
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_NETWORK
    assert "rerunning repeats no requests" in text(result)


@pytest.mark.parametrize("command", ["chaperone", "slides", "show-cohort"])
def test_offline_stubs_still_validate_the_config(tmp_path, config_dict, command):
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, [command, "--config", str(path)])
    assert result.exit_code == EXIT_NOT_IMPLEMENTED
    assert "not implemented yet" in text(result)


def test_show_cohort_warns_that_its_output_is_private(tmp_path, config_dict):
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["show-cohort", "--config", str(path)])
    assert "for your eyes only" in text(result)


# ------------------------------------------------------- init (TASKS.md task 2)


def fake_result(**overrides):
    """A canned InitResult. The real one is exercised in test_subject.py."""
    from tenuretrack.subject import InitResult, Institution, TopicProposal, draft_config

    result = InitResult(
        subject_name="Jane Doe",
        author_id="A100",
        institution=Institution(
            ror="https://ror.org/03r0ha626", name="University of X", type="education"
        ),
        start_year=2019,
        topics=(
            TopicProposal(id="T10001", name="Topic A", papers=6, subfield="Chemistry"),
            TopicProposal(id="T10002", name="Topic B", papers=4, subfield="Chemistry"),
        ),
        label="chemistry",
        orcid="0000-0002-1825-0097",
        works_seen=12,
        window_works=10,
        current_career_year=8,
        **overrides,
    )
    return InitResult(**{**result.__dict__, "config": draft_config(result)})


class FakeClient:
    request_count = 4
    cache_hits = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def patch_init(monkeypatch, outcome):
    """Point the CLI at a fake client and a canned (or raising) init stage."""
    import tenuretrack.cli as cli

    monkeypatch.setattr(cli, "OpenAlexClient", lambda **_kwargs: FakeClient())

    def stage(_client, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(cli, "initialize", stage)


def init_args(tmp_path, *extra):
    return [
        "init",
        "--orcid",
        "0000-0002-1825-0097",
        "--institution",
        "University of X",
        "--start",
        "2019",
        "--config",
        str(tmp_path / "benchmark.yaml"),
        *extra,
    ]


def test_init_writes_a_config_that_loads(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_init(monkeypatch, fake_result())
    result = runner.invoke(app, init_args(tmp_path))
    assert result.exit_code == 0, text(result)

    written = tmp_path / "benchmark.yaml"
    loaded = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert loaded["subject"]["orcid"] == "0000-0002-1825-0097"
    assert [t["id"] for t in loaded["subfield"]["topics"]] == ["T10001", "T10002"]


def test_init_explains_the_file_it_wrote(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_init(monkeypatch, fake_result())
    result = runner.invoke(app, init_args(tmp_path))
    out = text(result)
    assert "T10001" in out
    assert "Check the topics" in out
    assert "OpenAlex requests: 4" in out


def test_init_leaves_a_comment_a_reader_can_act_on(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_init(monkeypatch, fake_result())
    runner.invoke(app, init_args(tmp_path))
    body = (tmp_path / "benchmark.yaml").read_text(encoding="utf-8")
    assert body.startswith("#")
    assert "excluded_topics" in body


def test_init_will_not_quietly_overwrite_your_topic_choices(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    existing = tmp_path / "benchmark.yaml"
    existing.write_text("keep: me\n", encoding="utf-8")
    patch_init(monkeypatch, fake_result())
    result = runner.invoke(app, init_args(tmp_path))
    assert result.exit_code == EXIT_BAD_CONFIG
    assert "--force" in text(result)
    assert existing.read_text(encoding="utf-8") == "keep: me\n"


def test_force_starts_over(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    (tmp_path / "benchmark.yaml").write_text("keep: me\n", encoding="utf-8")
    patch_init(monkeypatch, fake_result())
    result = runner.invoke(app, init_args(tmp_path, "--force"))
    assert result.exit_code == 0, text(result)
    assert "subject" in yaml.safe_load((tmp_path / "benchmark.yaml").read_text())


def test_init_reports_a_problem_the_user_can_fix(monkeypatch, tmp_path):
    from tenuretrack.subject import InitError

    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_init(monkeypatch, InitError("OpenAlex has no author record for ORCID X"))
    result = runner.invoke(app, init_args(tmp_path))
    assert result.exit_code == EXIT_BAD_CONFIG
    assert "no author record" in text(result)
    assert not (tmp_path / "benchmark.yaml").exists()


def test_init_exits_separately_when_the_quota_runs_out(monkeypatch, tmp_path):
    from tenuretrack.cli import EXIT_NETWORK
    from tenuretrack.openalex import QuotaExhausted

    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    patch_init(monkeypatch, QuotaExhausted("https://api.openalex.org/works", 3600.0))
    result = runner.invoke(app, init_args(tmp_path))
    assert result.exit_code == EXIT_NETWORK
    assert "rerunning repeats no requests" in text(result)
