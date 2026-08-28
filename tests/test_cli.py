"""The CLI surface. Task 1 registers the commands; the stages come later."""

from __future__ import annotations

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


def test_run_reports_the_stage_that_is_not_built_yet(monkeypatch, tmp_path, config_dict):
    monkeypatch.setenv(MAILTO_ENV_VAR, "tester@example.edu")
    path = write_config(tmp_path, config_dict)
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == EXIT_NOT_IMPLEMENTED
    assert "not implemented yet" in text(result)


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
