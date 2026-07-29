"""Logging and the shared progress display for concurrent downloads."""

import logging
import threading

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from . import constants


def format_bytes(bytes_count: int) -> str:
    """Format bytes into human-readable string with appropriate unit.

    Args:
        bytes_count: Number of bytes

    Returns:
        Formatted string like "1.5 GB", "250 MB", "500 KB", etc.
    """
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    size = float(bytes_count)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def _make_console() -> Console:
    """Single console shared by logging and the progress display, so log
    lines render above the live bars instead of tearing through them."""
    console = Console()
    console.width = (
        min(console.width, constants.CONSOLE_WIDTH_LIMIT)
        if console.width
        else constants.CONSOLE_WIDTH_LIMIT
    )
    return console


_console = _make_console()


class DownloadProgressManager:
    """Shared rich Progress display for concurrent downloads.

    Rows have an explicit lifecycle: begin() registers a row and starts the
    display, update() advances it monotonically, finish() removes the row
    and stops the display when no downloads remain. Updates for unregistered
    keys are ignored, so a straggler thread can't resurrect a stopped
    display or create duplicate rows.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._progress: Progress | None = None
        self._tasks: dict[str, TaskID] = {}
        self._completed: dict[str, int] = {}

    def _get_progress(self) -> Progress:
        """Create the Progress lazily. Caller must hold the lock."""
        if self._progress is None:
            self._progress = Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=None),
                TaskProgressColumn(),
                TextColumn("•"),
                DownloadColumn(),
                TextColumn("•"),
                TransferSpeedColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                TextColumn("•"),
                TimeRemainingColumn(),
                console=_console,
                expand=True,
            )
        return self._progress

    def begin(self, key: str, description: str, total: int | None = None) -> None:
        """Register a download row and start the display if needed.

        Args:
            key: Unique key for this download (e.g. the destination path).
                Two concurrent downloads may share a display name, so the
                name alone can't identify the row. Re-registering an
                existing key resets its row instead of adding a duplicate.
            description: Display name for the row.
            total: Total size in bytes; None renders an indeterminate bar
                until update() supplies the size.
        """
        with self._lock:
            progress = self._get_progress()
            self._completed[key] = 0
            if key in self._tasks:
                progress.reset(
                    self._tasks[key],
                    total=total,
                    description=f"Downloading {description}",
                )
            else:
                self._tasks[key] = progress.add_task(
                    f"Downloading {description}", total=total
                )
            if not progress.live.is_started:
                progress.start()

    def update(self, key: str, completed: int, total: int | None = None) -> None:
        """Advance a download's row.

        Monotonic: smaller values (stale sums from racing chunk callbacks)
        are ignored — reset() is the explicit way back. Unknown keys are
        ignored so a late callback can't resurrect a stopped display.
        """
        with self._lock:
            task_id = self._tasks.get(key)
            if task_id is None or self._progress is None:
                return
            if completed < self._completed.get(key, 0):
                return
            self._completed[key] = completed
            if total is not None and total > 0:
                self._progress.update(task_id, completed=completed, total=total)
            else:
                self._progress.update(task_id, completed=completed)

    def reset(self, key: str, total: int | None = None) -> None:
        """Restart a row from zero, including its clock and speed samples
        (e.g. a chunked download falling back to a single connection)."""
        with self._lock:
            task_id = self._tasks.get(key)
            if task_id is None or self._progress is None:
                return
            self._completed[key] = 0
            self._progress.reset(task_id, total=total)

    def finish(self, key: str, success: bool = True) -> None:
        """Remove a download's row and stop the display when none remain.

        A successful download leaves a one-line summary in the scrollback
        (the live rows themselves disappear with the display).
        """
        with self._lock:
            task_id = self._tasks.pop(key, None)
            self._completed.pop(key, None)
            progress = self._progress
            if progress is None:
                return

            if task_id is not None:
                task = next((t for t in progress.tasks if t.id == task_id), None)
                if success and task is not None and task.completed > 0:
                    elapsed = f" in {task.elapsed:.1f}s" if task.elapsed else ""
                    name = task.description.removeprefix('Downloading ')
                    progress.console.print(
                        f"[green]✓[/green] {name}"
                        f" ({format_bytes(int(task.completed))}{elapsed})"
                    )
                progress.remove_task(task_id)

            if not self._tasks and progress.live.is_started:
                progress.stop()


# Module-level singleton used by the downloaders
download_progress = DownloadProgressManager()


# Setup logging
def setup_logger() -> logging.Logger:
    """Setup and return a logger with the given name."""
    logger = logging.getLogger('updatechecker')

    # If no handlers, add a default one
    if not logger.handlers:
        # Same console as the progress display: log lines from worker
        # threads render above the live bars instead of tearing them
        handler = RichHandler(
            console=_console,
            show_time=False,
            show_path=False,
            rich_tracebacks=True,
        )
        handler.setFormatter(logging.Formatter('%(name)s - %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


# Create the module-level log instance
log = setup_logger()
