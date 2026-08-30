"""The `tenuretrack` command line.

Task 1 registered every subcommand and wired up config loading and the
polite-pool check. Task 2 filled in `init`. The remaining stages land in later
tasks, and each stub says which task will fill it in.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import typer
import yaml

from tenuretrack import __version__
from tenuretrack.career import build_starts, candidates_worth_asking
from tenuretrack.chaperone import build_chaperone
from tenuretrack.config import Config, ConfigError, load_config
from tenuretrack.metrics import build_benchmarks
from tenuretrack.openalex import (
    DEFAULT_CACHE_DIR,
    MailtoNotConfigured,
    OpenAlexClient,
    OpenAlexError,
    QuotaExhausted,
    mailto_from_env,
)
from tenuretrack.pdf_report import build_pdf_report
from tenuretrack.peers import enough_people
from tenuretrack.pool import build_pool
from tenuretrack.report import build_report
from tenuretrack.slides import build_slides, export_pdf, load_slide_data
from tenuretrack.subject import InitError, format_result, initialize

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
EXIT_NETWORK = 3

CONFIG_HEADER = """\
# Written by `tenuretrack init`. Edit before running.
#
# The topic list is the one choice that matters. It defines who ends up in the
# cohort, so drop anything here that is not really your field, and move it to
# excluded_topics so the report can say what was left out.
"""

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
EXTENSION_OPTION = typer.Option(
    0,
    "--clock-extension",
    help=(
        "Years the tenure clock was stopped (parental or medical leave, a "
        "pandemic extension). Moves the comparison back that many years."
    ),
)
CACHE_OPTION = typer.Option(
    DEFAULT_CACHE_DIR,
    "--cache-dir",
    help="Where OpenAlex responses are cached, so a rerun repeats no requests.",
)
RESULTS_OPTION = typer.Option(
    None, "--results-dir", help="Where the pipeline wrote its output."
)
PDF_OPTION = typer.Option(
    True, "--pdf/--no-pdf", help="Also export a PDF if LibreOffice is present."
)
DATA_OPTION = typer.Option(
    Path("data"),
    "--data-dir",
    help="Where the candidate pool is kept. Holds names, so it is never committed.",
)


def _budget_line(client: OpenAlexClient) -> str:
    """What the day's OpenAlex budget has left, when the server said so.

    OpenAlex bills per call against a daily budget that resets at midnight UTC,
    so a run that stops early is usually the budget, not a bug.
    """
    remaining = client.budget_remaining
    if remaining is None:
        return ""
    limit = f" of {client.budget_limit}" if client.budget_limit else ""
    return f"; daily budget left: {remaining}{limit}"


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
    clock_extension: int = EXTENSION_OPTION,
    config_path: Path = INIT_CONFIG_OPTION,
    cache_dir: Path = CACHE_OPTION,
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing config. Any topic edits in it are lost.",
    ),
) -> None:
    """Resolve the subject, propose subfield topics, and draft benchmark.yaml."""
    mailto = _require_mailto()
    if config_path.exists() and not force:
        _echo_err(
            f"{config_path} already exists, and rewriting it would throw away the "
            "topics you chose. Pass --force to start over, or edit the file."
        )
        raise typer.Exit(code=EXIT_BAD_CONFIG)

    with OpenAlexClient(mailto=mailto, cache_dir=cache_dir) as client:
        try:
            result = initialize(
                client,
                orcid=orcid,
                institution=institution,
                start_year=start,
                clock_extension_years=clock_extension,
            )
        except InitError as exc:
            _echo_err(str(exc))
            raise typer.Exit(code=EXIT_BAD_CONFIG) from exc
        except QuotaExhausted as exc:
            _echo_err(str(exc))
            raise typer.Exit(code=EXIT_NETWORK) from exc
        except OpenAlexError as exc:
            _echo_err(f"OpenAlex request failed: {exc}")
            raise typer.Exit(code=EXIT_NETWORK) from exc
        requests, hits = client.request_count, client.cache_hits
        budget = _budget_line(client)

    _write_config(config_path, result.config)
    typer.echo(format_result(result))
    typer.echo("")
    typer.echo(f"Wrote {config_path}. Check the topics, then run `tenuretrack run`.")
    typer.echo(f"OpenAlex requests: {requests} (served from cache: {hits}){budget}")


def _write_config(path: Path, config: dict) -> None:
    """Write the draft, then load it back so a bad draft fails here, not later."""
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    path.write_text(CONFIG_HEADER + body, encoding="utf-8")
    try:
        load_config(path)
    except ConfigError as exc:
        _echo_err(
            f"init wrote {path} but it does not validate. This is a bug; please "
            f"report it at github.com/sp8rks/tenuretrack/issues.\n{exc}"
        )
        raise typer.Exit(code=EXIT_BAD_CONFIG) from exc


@app.command()
def run(
    config_path: Path = CONFIG_OPTION,
    cache_dir: Path = CACHE_OPTION,
    data_dir: Path = DATA_OPTION,
    refresh: bool = typer.Option(
        False, "--refresh", help="Gather the candidate pool again from scratch."
    ),
) -> None:
    """Build the cohort, compute the norms, and write the report."""
    config = _load(config_path)
    mailto = _require_mailto()
    problems = config.unresolved()
    for problem in problems:
        _echo_err(f"config is not ready to run: {problem}")
    if problems:
        raise typer.Exit(code=EXIT_BAD_CONFIG)

    with OpenAlexClient(mailto=mailto, cache_dir=cache_dir) as client:
        try:
            result = build_pool(
                client,
                config,
                data_dir=data_dir,
                on_progress=typer.echo,
                refresh=refresh,
            )
            members = build_starts(
                client,
                result.kept,
                config,
                result.funnel,
                data_dir=data_dir,
                on_progress=typer.echo,
                refresh=refresh,
            )
            asked = [
                c.author_id
                for c in candidates_worth_asking(
                    result.kept, config.cohort.start_window
                )
            ]
            benchmarks = build_benchmarks(
                client,
                members,
                asked,
                config,
                data_dir=data_dir,
                on_progress=typer.echo,
            )
            if config.output.chaperone:
                build_chaperone(
                    benchmarks,
                    {c.author_id: e for c, e in members},
                    config,
                    on_progress=typer.echo,
                )
            report_path, subject, horizon = build_report(
                client,
                config,
                benchmarks,
                result.funnel,
                this_year=_dt.date.today().year,
                on_progress=typer.echo,
            )
        except QuotaExhausted as exc:
            # Everything fetched is cached and the funnel so far is on disk, so
            # the rerun picks up here rather than starting over.
            result_so_far = locals().get("result")
            if result_so_far is not None:
                result_so_far.funnel.write_csv(result_so_far.funnel_path)
            _echo_err(str(exc))
            raise typer.Exit(code=EXIT_NETWORK) from exc
        except OpenAlexError as exc:
            _echo_err(f"OpenAlex request failed: {exc}")
            raise typer.Exit(code=EXIT_NETWORK) from exc
        requests, hits = client.request_count, client.cache_hits
        budget = _budget_line(client)

    # Next to the report that was actually written, not wherever the config
    # points: the two must not be able to land in different directories.
    build_pdf_report(report_path.parent, config, on_progress=typer.echo)

    result.funnel.write_csv(result.funnel_path)
    _echo_funnel(result.funnel)
    typer.echo(f"OpenAlex requests: {requests} (served from cache: {hits}){budget}")
    typer.echo(f"{len(members)} people placed on the tenure clock.")
    if config.cohort.peer_group_size > 0:
        thin = enough_people(len(members))
        if thin:
            _echo_err(thin)
    typer.echo(
        f"Wrote {benchmarks.csv_path.name} and {benchmarks.md_path.name} "
        f"({benchmarks.institutions} institutions in the cohort)."
    )
    typer.echo(
        f"Wrote {report_path.name}: {config.subject.name} at career year "
        f"{horizon}, {subject.pubs} articles and {subject.led} led."
    )


def _echo_funnel(funnel) -> None:
    typer.echo("")
    typer.echo("Funnel:")
    for step in funnel.steps:
        typer.echo(
            f"  {step.step}. {step.label}: {step.kept} left ({step.dropped} out)"
        )


@app.command()
def chaperone(config_path: Path = CONFIG_OPTION) -> None:
    """Compare venue quality on led versus co-authored papers."""
    _load(config_path)
    _not_implemented("chaperone", "task 7")


@app.command()
def slides(
    config_path: Path = CONFIG_OPTION,
    results_dir: Path = RESULTS_OPTION,
    pdf: bool = PDF_OPTION,
) -> None:
    """Build the six-slide deck from an existing results directory.

    Reads only what `run` already wrote. Nothing is recomputed, so the deck
    cannot disagree with the report.
    """
    config = _load(config_path)
    results = results_dir or config.output.dir
    data = load_slide_data(results, config)
    if not data.subject:
        _echo_err(
            f"no {results}/subject.csv, so there is nothing to put on a slide. "
            "Run `tenuretrack run` first."
        )
        raise typer.Exit(code=EXIT_BAD_CONFIG)

    deck = build_slides(data, results, on_progress=typer.echo)
    build_pdf_report(results, config, on_progress=typer.echo)
    if pdf:
        export_pdf(deck, on_progress=typer.echo)


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
