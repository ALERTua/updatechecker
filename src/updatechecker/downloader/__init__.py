"""Downloader package with HTTP and GitHub implementations.

This package provides downloaders for different URL types:
- HttpDownloader: Generic HTTP/HTTPS downloads using httpx
- GitHubDownloader: GitHub-specific downloads using PyGithub

Usage:
    from updatechecker.downloader import HttpDownloader, GitHubDownloader

    # For generic URLs
    http_dl = HttpDownloader()
    http_dl.download_file_from_url(url, destination)

    # For GitHub repositories
    gh_dl = GitHubDownloader(token="your_token")
    package = gh_dl.validate_package("owner/repo")
    release = gh_dl.get_latest_release(package)
    asset_url = gh_dl.get_asset_url(release, r"pattern.*\\.zip")
"""

from .factory import DownloaderFactory
from .http import HttpDownloader
from .github import GitHubDownloader

__all__ = [
    'HttpDownloader',
    'GitHubDownloader',
    'DownloaderFactory',
]
