"""Custom logger with Rich progress bar support for downloads."""

import logging
from typing import Optional

from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
)
from rich.console import Console

console = Console()

# Global progress instance for downloads
_progress: Optional[Progress] = None
_download_tasks: dict[str, int] = {}


def get_progress() -> Progress:
    """Get or create the global Progress instance for downloads."""
    global _progress
    if _progress is None:
        _progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
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
    global _download_tasks

    progress = get_progress()

    # Start progress if not running
    if not progress.live.is_started:
        progress.start()

    # Get or create task for this file
    if filename not in _download_tasks:
        _download_tasks[filename] = progress.add_task(
            f"Downloading {filename}", total=total
        )

    task_id = _download_tasks[filename]

    # Update the task with new progress
    # If downloaded >= total, the download is complete
    if downloaded >= total:
        progress.update(task_id, completed=total)
    else:
        progress.update(task_id, completed=downloaded)


def remove_download_task(filename: str):
    """Remove a download task from tracking."""
    global _download_tasks
    if filename in _download_tasks:
        del _download_tasks[filename]


def clear_download_tasks():
    """Clear all download tasks."""
    global _download_tasks
    _download_tasks.clear()


# Custom logger class that extends logging.Logger
class UpdateCheckerLogger(logging.Logger):
    """Custom logger with additional methods for progress tracking."""

    def warning_msg(self, message: str, *args, **kwargs):
        """Deprecated: Use warning() instead."""
        self.warning(message, *args, **kwargs)

    def update_download_progress(self, filename: str, downloaded: int, total: int):
        """Update download progress (delegates to global progress tracker)."""
        update_download_progress(filename, downloaded, total)


# Setup logging
def setup_logger(name: str) -> logging.Logger:
    """Setup and return a logger with the given name."""
    logger = logging.getLogger(name)

    # If no handlers, add a default one
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


# Create the module-level log instance
log = setup_logger(__name__)

# Add progress control methods to the log instance for convenience
log.update_download_progress = update_download_progress
log.start_download_progress = start_download_progress
log.stop_download_progress = stop_download_progress
log.get_progress = get_progress
