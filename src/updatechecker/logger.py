"""Custom logger with Rich progress bar support for downloads."""

import logging
import threading
import time

from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    ProgressColumn,
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


class ByteSizeColumn(ProgressColumn):
    """Custom column that displays file size with appropriate units."""

    def __init__(self, unit: str = "auto"):
        super().__init__()
        self.unit = unit  # "auto" for adaptive, or specific unit

    def render(self, task):
        """Render the file size with appropriate units."""
        from rich.text import Text

        total = task.total or 0
        completed = task.completed or 0

        if self.unit == "auto":
            # Use adaptive formatting
            total_str = format_bytes(total)
            completed_str = format_bytes(completed)
        else:
            # Use fixed unit based on self.unit
            if self.unit == "KB":
                completed_str = f"{completed / 1024:.2f}"
                total_str = f"{total / 1024:.2f}"
            elif self.unit == "MB":
                completed_str = f"{completed / 1024 / 1024:.2f}"
                total_str = f"{total / 1024 / 1024:.2f}"
            elif self.unit == "GB":
                completed_str = f"{completed / 1024 / 1024 / 1024:.2f}"
                total_str = f"{total / 1024 / 1024 / 1024:.2f}"
            else:
                # Unknown unit, fallback to auto
                total_str = format_bytes(total)
                completed_str = format_bytes(completed)

        return Text(f"{completed_str}/{total_str}", style="progress.percentage")


class DownloadSpeedColumn(ProgressColumn):
    """Custom column that displays download speed."""

    def __init__(self):
        super().__init__()
        self._task_id_to_filename = {}

    def render(self, task):
        """Render the download speed."""
        from rich.text import Text

        # Use task.id to look up the speed
        task_id = task.id
        speed = _download_speeds.get(task_id, 0)

        if speed > 0:
            speed_str = format_bytes(int(speed)) + "/s"
        else:
            speed_str = "--"

        return Text(f"{speed_str}", style="progress.percentage")


# Global progress instance for downloads
_progress: Progress | None = None
_download_tasks: dict[str, int] = {}
_download_start_times: dict[str, float] = {}  # filename -> start time
_download_speeds: dict[int, float] = {}  # task_id -> speed in bytes per second
_download_lock = threading.Lock()  # Lock for thread-safe access to global state


def get_progress() -> Progress:
    """Get or create the global Progress instance for downloads."""
    global _progress
    if _progress is None:
        # Limit console width to 300 characters max
        console = Console()
        console.width = (
            (min(console.width, constants.CONSOLE_WIDTH_LIMIT))
            if console.width
            else constants.CONSOLE_WIDTH_LIMIT
        )

        _progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            ByteSizeColumn(unit="auto"),
            TextColumn("•"),
            DownloadSpeedColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
            expand=True,
        )
    return _progress


def start_download_progress():
    """Start the download progress display."""
    global _progress
    if _progress is not None and not _progress.live.is_started:
        _progress.start()


def stop_download_progress():
    """Stop the download progress display."""
    global _progress
    if _progress is not None and _progress.live.is_started:
        _progress.stop()


def update_download_progress(filename: str, downloaded: int, total: int):
    """Update the progress bar for a download.

    Args:
        filename: Name of the file being downloaded
        downloaded: Number of bytes downloaded
        total: Total size of the file in bytes
    """
    global _download_tasks, _download_start_times, _download_speeds

    with _download_lock:
        progress = get_progress()

        # Start progress if not running
        if not progress.live.is_started:
            progress.start()

        # Get or create task for this file - only create if doesn't exist
        if filename not in _download_tasks:
            _download_start_times[filename] = time.time()
            task_id = progress.add_task(f"Downloading {filename}", total=total)
            _download_tasks[filename] = task_id
            _download_speeds[task_id] = 0
        else:
            task_id = _download_tasks[filename]

        # Calculate download speed
        start_time = _download_start_times.get(filename, time.time())
        elapsed = time.time() - start_time
        speed = downloaded / elapsed if elapsed > 0 else 0
        _download_speeds[task_id] = speed

        # Update the task with new progress
        # If downloaded >= total, the download is complete
        if downloaded >= total:
            progress.update(task_id, completed=total)
        else:
            progress.update(task_id, completed=downloaded)


def remove_download_task(filename: str):
    """Remove a download task from tracking."""
    global _download_tasks, _download_start_times, _download_speeds
    with _download_lock:
        if filename in _download_tasks:
            task_id = _download_tasks[filename]
            del _download_speeds[task_id]
            del _download_tasks[filename]
        if filename in _download_start_times:
            del _download_start_times[filename]


def clear_download_tasks():
    """Clear all download tasks."""
    global _download_tasks, _download_start_times, _download_speeds
    with _download_lock:
        _download_tasks.clear()
        _download_start_times.clear()
        _download_speeds.clear()


# Setup logging
def setup_logger() -> logging.Logger:
    """Setup and return a logger with the given name."""
    logger = logging.getLogger('updatechecker')

    # If no handlers, add a default one
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(name)s - %(levelname)s - %(message)s',
            # datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # logger.addHandler(RichHandler(show_time=True, rich_tracebacks=True))
        logger.setLevel(logging.INFO)

    return logger


# Create the module-level log instance
log = setup_logger()

# Add progress control methods to the log instance for convenience
log.update_download_progress = update_download_progress
log.start_download_progress = start_download_progress
log.stop_download_progress = stop_download_progress
log.get_progress = get_progress
log.remove_download_task = remove_download_task
log.clear_download_tasks = clear_download_tasks
