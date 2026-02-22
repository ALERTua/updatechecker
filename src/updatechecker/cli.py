"""Command-line interface argument parsing using Typer."""

from pathlib import Path
from typing import Annotated
import typer
import logging

from .updatechecker import updatechecker, get_default_config_path
from .logger import log

app = typer.Typer(
    name="updatechecker",
    help="Check and update files from configured sources",
    add_completion=True,
)


def parse_arg_entries(entries_str: str | None) -> list[str] | None:
    """Parse comma-separated entries string into list."""
    if entries_str is None:
        return None
    return [e.strip() for e in entries_str.split(",") if e.strip()]


@app.command()
def cli(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file (default: ~/updatechecker.yaml)",
        ),
    ] = None,
    async_mode: Annotated[
        bool,
        typer.Option("--async/--no-async", help="Enable/disable parallel processing"),
    ] = True,
    threads: Annotated[
        int | None,
        typer.Option(
            "--threads",
            "-t",
            help="Number of threads for parallel processing (default: CPU count - 1)",
            min=1,
        ),
    ] = None,
    entries: Annotated[
        str | None,
        typer.Option(
            "--entries",
            "-e",
            help="Comma-separated list of entry names to check (default: all)",
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Force re-download, skip HEAD/MD5 checks")
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output (alias for --log-level DEBUG)",
        ),
    ] = False,
    gh_token: Annotated[
        str | None,
        typer.Option(
            "--gh-token",
            help="GitHub token for API requests (overrides config and env var GITHUB_TOKEN)",
        ),
    ] = None,
) -> None:
    """UpdateChecker - Check and update files from configured sources."""
    if verbose:
        log.setLevel(logging.DEBUG)

    # Parse entries filter
    entries_list = parse_arg_entries(entries)

    # Log configuration
    log.debug(f"Config: {config or get_default_config_path()}")
    log.debug(f"Async: {async_mode}")
    log.debug(f"Threads: {threads}")
    log.debug(f"Entries: {entries_list}")
    log.debug(f"Force: {force}")
    log.debug(f"GH Token: {'provided' if gh_token else 'not provided'}")

    # Call the main function with parsed arguments
    updatechecker(
        config_path=config,
        _async=async_mode,
        threads=threads,
        entries=entries_list,
        force=force,
        gh_token=gh_token,
    )


if __name__ == "__main__":
    app()
