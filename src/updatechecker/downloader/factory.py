"""Downloader factory for creating appropriate downloader based on entry type."""

from ..config import Entry
from .github import GitHubDownloader
from .http import HttpDownloader


class DownloaderFactory:
    """Factory for creating appropriate downloader based on entry type.

    Determines which downloader to use based on the entry configuration:
    - If entry.git_asset is set: use GitHubDownloader (handles GitHub API + downloads)
    - Otherwise: use HttpDownloader (generic HTTP downloads)
    """

    @staticmethod
    def create(
        entry: Entry, gh_token: str | None = None
    ) -> HttpDownloader | GitHubDownloader:
        """Create appropriate downloader for the given entry.

        Args:
            entry: Configuration entry to determine downloader type
            gh_token: Optional GitHub token for API requests

        Returns:
            HttpDownloader or GitHubDownloader instance
        """
        if entry.git_asset is not None:
            return GitHubDownloader(token=gh_token)
        return HttpDownloader()
