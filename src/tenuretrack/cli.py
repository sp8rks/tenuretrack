"""The `tenuretrack` command line.

Task 1 registers every subcommand and wires up the parts that already exist
(config loading, the polite-pool check). The stages themselves land in later
tasks, and each stub says which task will fill it in.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tenuretrack import __version__
from tenuretrack.config import Config, ConfigError, load_config
from tenuretrack.openalex import MailtoNotConfigured, mailto_from_env

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Subfield publication norms for the tenure clock, computed from OpenAlex. "
        "Aggregates only."
    ),
)

EXIT_NOT_IMPLEMENTED = 1
EXIT_BAD_CONFIG = 2

CONFIG_OPTION = typer.Option(
    Path("benchmark.yaml"),
    "--config",
    "-c",
    help="Path to the subject spec (see benchmark.example.yaml).",
)
INIT_CONFIG_OPTION = typer.Option(
    Path("benchmark.yaml"),
    "--config",
    "-c",
    help="Where to write the draft subject spec.",
)


def _echo_err(message: str) -> None:
    typer.echo(message, err=True)


def _load(config_path: Path) -> Config:
    """Load a config, or exit with the list of problems to fix."""
    try:
        return load_config(config_path)
    except ConfigError as exc:
        _echo_err(str(exc))
        raise typer.Exit(code=EXIT_BAD_CONFIG) from exc


def _require_mailto() -> str:
    """Refuse to start a network stage without a polite-pool address."""
    try:
        return mailto_from_env()
    except MailtoNotConfigured as exc:
        _echo_err(str(exc))
        raise typer.Exit(code=EXIT_BAD_CONFIG) from exc


def _not_implemented(stage: str, task: str) -> None:
    _echo_err(f"{stage} is not implemented yet (TASKS.md, {task}).")
    raise typer.Exit(code=EXIT_NOT_IMPLEMENTED)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tenuretrack {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Build a subfield cohort and place one record against it."""


@app.command()
def init(
    orcid: str = typer.Option(..., "--orcid", help="The subject's ORCID."),
    institution: str = typer.Option(
        ..., "--institution", help="The subject's institution, by name or ROR."
    ),
    start: int = typer.Option(
        ..., "--start", help="First calendar year of the tenure-line appointment."
    ),
    config_path: Path = INIT_CONFIG_OPTION,
) -> None:
    """Resolve the subject, propose subfield topics, and draft benchmark.yaml."""
    _require_mailto()
    _not_implemented("init", "task 2")


@app.command()
def run(config_path: Path = CONFIG_OPTION) -> None:
    """Build the cohort, compute the norms, and write the report."""
    config = _load(config_path)
    _require_mailto()
    for problem in config.unresolved():
        _echo_err(f"config is not ready to run: {problem}")
    if config.unresolved():
        raise typer.Exit(code=EXIT_BAD_CONFIG)
    _not_implemented("run", "tasks 3 to 6")


@app.command()
def chaperone(config_path: Path = CONFIG_OPTION) -> None:
    """Compare venue quality on led versus co-authored papers."""
    _load(config_path)
    _not_implemented("chaperone", "task 7")


@app.command()
def slides(config_path: Path = CONFIG_OPTION) -> None:
    """Build the six-slide deck from an existing results directory."""
    _load(config_path)
    _not_implemented("slides", "task 8")


@app.command("show-cohort")
def show_cohort(config_path: Path = CONFIG_OPTION) -> None:
    """Print the cohort to the terminal for your own sanity check.

    This is the one place names appear. It prints and never writes a file.
    """
    _load(config_path)
    _echo_err(
        "Reminder: show-cohort output is for your eyes only. Cohort members did "
        "not ask to be listed, so do not paste it into an issue, a PR, or a slide."
    )
    _not_implemented("show-cohort", "task 4")


if __name__ == "__main__":  # pragma: no cover
    app()
