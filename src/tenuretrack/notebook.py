"""Glue for the Google Colab notebook (`notebooks/tenuretrack_colab.ipynb`).

Most faculty who want their own numbers do not want to clone a repository,
install Python, and hand-edit YAML. The notebook drives the same CLI stages a
terminal user runs, and these functions are the small pieces of glue it needs:
setting the polite-pool address, picking which proposed topics to keep, and
packaging `results/` for download after the guardrail has cleared it.

The glue lives here rather than inside notebook cells so that it is covered by
`make test`. Nothing here touches the network. The only notebook-environment
import is a guarded one for Colab's secret store, inside the function that
needs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from pathlib import Path

import yaml

from tenuretrack.config import Config, ConfigError, Topic, load_config
from tenuretrack.guardrail import assert_directory_aggregates_only
from tenuretrack.openalex import (
    API_KEY_ENV_VAR,
    FREE_KEYLESS_BUDGET,
    MAILTO_ENV_VAR,
    mailto_from_env,
)

__all__ = [
    "NotebookError",
    "describe_config",
    "keep_topics",
    "list_results",
    "numbered_topics",
    "parse_selection",
    "prompt_for_api_key",
    "run_cli",
    "set_api_key",
    "set_peer_group",
    "set_mailto",
    "zip_results",
]

COLAB_SECRET_NAME = "OPENALEX_API_KEY"
"""Name to look for in Colab's secret store (the key icon in the left sidebar).

A secret lives in the user's Google account, not in the notebook file, so it
survives sharing the notebook and does not travel with it.
"""

ERROR_TAIL_LINES = 12
"""How much of a failed stage's output to quote back in the exception."""


class NotebookError(RuntimeError):
    """A notebook step cannot proceed, worded for a first-time user."""


def run_cli(
    *args: object,
    on_line: Callable[[str], None] = print,
    cwd: str | Path | None = None,
) -> str:
    """Run a `tenuretrack` subcommand, printing as it goes, and check it worked.

    A notebook cell that shells out with `!tenuretrack ...` prints the error and
    carries on as if nothing happened, so the run fails silently in one cell and
    raises something unreadable two cells later. This runs the same command,
    streams its output into the cell so a long stage shows progress, and raises
    `NotebookError` the moment the command exits nonzero.
    """
    command = [sys.executable, "-m", "tenuretrack.cli", *[str(a) for a in args]]
    lines: list[str] = []
    try:
        process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd is not None else None,
        )
    except OSError as exc:
        raise NotebookError(f"could not start tenuretrack: {exc}") from exc

    with process:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\n")
            lines.append(line)
            on_line(line)

    if process.returncode != 0:
        stage = str(args[0]) if args else "tenuretrack"
        tail = "\n".join(lines[-ERROR_TAIL_LINES:])
        raise NotebookError(
            f"the `{stage}` step did not finish (exit code {process.returncode}). "
            f"What it said:\n{tail}"
        )
    return "\n".join(lines)


def set_mailto(address: str, env: MutableMapping[str, str] | None = None) -> str:
    """Put the polite-pool contact address in the environment and validate it.

    OpenAlex asks every caller to identify itself. The address is sent to
    OpenAlex and nowhere else, and it is never written into the repository.
    """
    env = os.environ if env is None else env
    env[MAILTO_ENV_VAR] = (address or "").strip()
    return mailto_from_env(env)


def prompt_for_api_key(
    env: MutableMapping[str, str] | None = None,
    *,
    read_secret: Callable[[str], str] | None = None,
    ask: Callable[[str], str] | None = None,
) -> str:
    """Get an OpenAlex key without ever writing it into the notebook file.

    A Colab form field (`#@param`) looks like the obvious place to type a key,
    and it is the wrong one: Colab saves form values back into the `.ipynb`, so
    a key typed there is written to the user's Drive and travels with the file
    if they share or download it. Nobody expects a text box to persist a
    secret.

    So this looks in three places, none of which is the notebook:

    1. The environment, if the key is already set.
    2. Colab's secret store, which lives in the user's Google account.
    3. A hidden prompt, which keeps the key out of the cell output too.

    Returns an empty string when there is no key, which is a supported way to
    run.
    """
    env = os.environ if env is None else env
    existing = (env.get(API_KEY_ENV_VAR) or "").strip()
    if existing:
        return existing

    if read_secret is None:
        read_secret = _colab_secret
    try:
        secret = (read_secret(COLAB_SECRET_NAME) or "").strip()
    except Exception:  # noqa: BLE001 - any failure just means "no secret here"
        secret = ""
    if secret:
        return secret

    if ask is None:
        import getpass

        ask = getpass.getpass
    try:
        return (ask("OpenAlex API key (press Enter to skip): ") or "").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _colab_secret(name: str) -> str:
    """Read one secret from Colab, or nothing at all when not in Colab."""
    from google.colab import userdata  # type: ignore[import-not-found]

    return userdata.get(name)


def set_api_key(key: str, env: MutableMapping[str, str] | None = None) -> str:
    """Put an optional OpenAlex API key in the environment, and say what it buys.

    Returns a line the notebook prints, because a blank key is a legitimate
    choice with a consequence the person should see before starting a long run,
    not an error.
    """
    env = os.environ if env is None else env
    key = (key or "").strip()
    if not key:
        env.pop(API_KEY_ENV_VAR, None)
        return (
            "No OpenAlex key, so the daily allowance is about "
            f"{FREE_KEYLESS_BUDGET} requests. The run will most likely stop "
            "partway and need continuing tomorrow. A free key at "
            "openalex.org/settings/api raises the allowance tenfold."
        )
    env[API_KEY_ENV_VAR] = key
    return "OpenAlex key set, so the daily allowance is ten times the default."


def describe_config(path: str | Path) -> str:
    """A plain-language summary of a `benchmark.yaml`, for display in a cell."""
    config = _load(path)
    subject = config.subject
    lines = [
        f"Subject: {subject.name}",
        f"Institution: {subject.institution_name}",
        f"Appointment began: {subject.start_year} "
        f"(currently career year {subject.current_career_year()})",
        f"Subfield: {config.subfield.label}",
        f"Cohort start window: {config.cohort.start_window[0]} to "
        f"{config.cohort.start_window[1]}",
        f"Benchmark horizon: through career year {config.cohort.horizon_years}",
        "",
        "Topics:",
    ]
    lines.extend(numbered_topics(config) or ["  (none yet, run the init step)"])
    problems = config.unresolved()
    if problems:
        lines.append("")
        lines.append("Still to settle before the run step:")
        lines.extend(f"  - {p}" for p in problems)
    return "\n".join(lines)


def numbered_topics(config: Config) -> list[str]:
    """The configured topics as `1. T10123  Name` lines the user can pick from."""
    return [
        f"  {i}. {topic.id}  {topic.name}".rstrip()
        for i, topic in enumerate(config.subfield.topics, start=1)
    ]


def parse_selection(selection: str, count: int) -> list[int]:
    """Turn a typed answer like `1, 2, 4` or `all` into 1-based topic numbers.

    Accepts commas, spaces, and ranges (`1-3`). Raises `NotebookError` with a
    readable message rather than a traceback, because the person typing this is
    in a browser and not reading a stack trace.
    """
    text = (selection or "").strip().lower()
    if count <= 0:
        raise NotebookError("there are no topics to choose from yet")
    if text in {"", "all", "*"}:
        return list(range(1, count + 1))

    picked: list[int] = []
    for chunk in text.replace(",", " ").split():
        if "-" in chunk[1:]:
            low_text, _, high_text = chunk.partition("-")
            low, high = _number(low_text, count), _number(high_text, count)
            span = range(low, high + 1) if low <= high else range(high, low + 1)
            picked.extend(span)
        else:
            picked.append(_number(chunk, count))

    unique = sorted(set(picked))
    if not unique:
        raise NotebookError("no topics were selected; type `all` to keep every topic")
    return unique


def _number(text: str, count: int) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise NotebookError(
            f"{text.strip()!r} is not one of the topic numbers; "
            f"type numbers from 1 to {count}, for example `1, 2, 4`"
        ) from None
    if not 1 <= value <= count:
        raise NotebookError(f"there is no topic {value}; the numbers run 1 to {count}")
    return value


def keep_topics(
    path: str | Path, selection: str | Iterable[int], *, note: str = ""
) -> tuple[Topic, ...]:
    """Keep the selected topics in `benchmark.yaml` and move the rest aside.

    Dropped topics move to `excluded_topics` rather than vanishing, so the
    report can say what the subfield deliberately left out. Returns the kept
    topics and rewrites the file in place.
    """
    path = Path(path)
    config = _load(path)
    topics = config.subfield.topics
    if isinstance(selection, str):
        numbers = parse_selection(selection, len(topics))
    else:
        numbers = sorted({int(n) for n in selection})
        for n in numbers:
            if not 1 <= n <= len(topics):
                raise NotebookError(
                    f"there is no topic {n}; the numbers run 1 to {len(topics)}"
                )
    if not numbers:
        raise NotebookError("keep at least one topic; a cohort needs a subfield")

    chosen = set(numbers)
    kept = tuple(topics[n - 1] for n in numbers)
    dropped = tuple(t for i, t in enumerate(topics, start=1) if i not in chosen)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    subfield = raw.setdefault("subfield", {})
    subfield["topics"] = [_topic_row(t) for t in kept]
    excluded = _existing_excluded(subfield)
    for topic in dropped:
        row = _topic_row(topic)
        if note:
            row["name"] = f"{row.get('name', '')} ({note})".strip()
        if row not in excluded:
            excluded.append(row)
    subfield["excluded_topics"] = excluded

    path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    _load(path)  # fail here, with the config error, rather than during the run
    return kept


def set_peer_group(path: str | Path, size: int) -> str:
    """Record a peer-institution restriction in `benchmark.yaml`.

    `size` of 0 turns it off, which is the default and the question most people
    mean. Returns the line the cell prints, because narrowing the cohort has a
    cost the person should see at the moment they choose it rather than in the
    funnel an hour later.
    """
    from tenuretrack.peers import MIN_PEER_COHORT

    size = int(size)
    if size < 0:
        raise NotebookError("how_many_schools cannot be negative")

    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("cohort", {})["peer_group_size"] = size
    path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    _load(path)  # fail here, with the config error, rather than during the run

    if size == 0:
        return "Comparing against your whole subfield, at every university."
    line = (
        f"Comparing against the {size} schools closest to yours in subfield "
        "output. This orders schools by output in your subfield, which is not "
        "a prestige ranking."
    )
    if size < 50:
        line += (
            f" {size} schools is narrow: a cohort runs to roughly two people "
            "per institution, so expect a small group. The run warns if it "
            f"leaves fewer than {MIN_PEER_COHORT} people."
        )
    return line


def _topic_row(topic: Topic) -> dict[str, str]:
    row: dict[str, str] = {"id": topic.id}
    if topic.name:
        row["name"] = topic.name
    return row


def _existing_excluded(subfield: Mapping[str, object]) -> list[dict[str, str]]:
    current = subfield.get("excluded_topics") or []
    rows: list[dict[str, str]] = []
    for item in current if isinstance(current, list) else []:
        if isinstance(item, str):
            rows.append({"id": item})
        elif isinstance(item, dict):
            rows.append({str(k): str(v) for k, v in item.items()})
    return rows


def list_results(results_dir: str | Path) -> list[Path]:
    """Every file the run wrote, sorted, so a cell can show what came out."""
    results_dir = Path(results_dir)
    if not results_dir.is_dir():
        return []
    return sorted(p for p in results_dir.rglob("*") if p.is_file())


def zip_results(
    results_dir: str | Path,
    dest: str | Path | None = None,
    *,
    cohort_names: Sequence[str] = (),
    cohort_ids: Sequence[str] = (),
) -> Path:
    """Bundle `results/` for download, but only after the guardrail clears it.

    The scan runs on the exact files that are about to leave the machine. If it
    finds an identifier or a prescriptive word, nothing is written.
    """
    results_dir = Path(results_dir)
    files = list_results(results_dir)
    if not files:
        raise NotebookError(
            f"there is nothing in {results_dir} to download yet; run the pipeline first"
        )
    assert_directory_aggregates_only(results_dir, cohort_names, cohort_ids)

    dest = Path(dest) if dest is not None else Path(f"{results_dir}.zip")
    if dest.parent != Path(""):
        dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, arcname=str(file.relative_to(results_dir)))
    return dest


def _load(path: str | Path) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        raise NotebookError(str(exc)) from exc
