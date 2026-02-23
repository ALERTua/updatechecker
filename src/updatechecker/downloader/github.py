"""GitHub downloader implementation using PyGithub for GitHub API interactions."""

import re

from github import Github, Auth
from github.GitRelease import GitRelease

from .http import HttpDownloader
from ..logger import log


class GitHubDownloader(HttpDownloader):
    """Downloader for GitHub repositories using PyGithub.

    Provides GitHub-specific functionality like:
    - Validating repository existence
    - Fetching releases
    - Finding asset download URLs by pattern
    """

    def __init__(self, token: str | None = None):
        """Initialize GitHub downloader.

        Args:
            token: Optional GitHub token for authenticated requests.
                   Without a token, you're limited to 60 requests/hour.
                   With a token, you get 5000 requests/hour.
        """
        super().__init__()
        self._token = token
        if token:
            auth = Auth.Token(token)
            self._client = Github(auth=auth)
        else:
            self._client = Github()

    def validate_package(self, package: str) -> str | None:
        """Validate GitHub package exists and return normalized name.

        Args:
            package: GitHub URL or package name (e.g., 'owner/repo')

        Returns:
            Normalized package name (owner/repo), or None if invalid
        """
        # Extract owner/repo from URL if needed
        if 'github' in package:
            match = re.search(r'(?<=github\.com/)[^/]+/[^/]+', package)
            if not match:
                log.warning(f"Could not extract owner/repo from '{package}'")
                return None
            package = match.group(0)

        try:
            repo = self._client.get_repo(package)
            return repo.full_name
        except Exception as e:
            log.warning(f"'{package}' is not a valid GitHub repository: {e}")
            return None

    def get_releases(self, package: str) -> list[GitRelease] | None:
        """Fetch all releases for a GitHub package.

        Args:
            package: GitHub package in 'owner/repo' format

        Returns:
            List of GitRelease objects, or None if error
        """
        try:
            repo = self._client.get_repo(package)
            releases = repo.get_releases()
            return list(releases)
        except Exception as e:
            token_str = 'with token' if self._token else 'without token'
            log.warning(f"GitHub API error for package '{package}' {token_str}: {e}")
            return None

    def get_latest_release(self, package: str) -> GitRelease | None:
        """Get the latest release for a GitHub package.

        Args:
            package: GitHub package in 'owner/repo' format

        Returns:
            GitRelease object, or None if no releases or error
        """
        releases = self.get_releases(package)
        if not releases:
            log.debug(f"No releases found for '{package}'")
            return None

        return releases[0]

    def get_asset_url(self, release: GitRelease, asset_pattern: str) -> str | None:
        """Get the download URL for an asset matching the given pattern.

        Args:
            release: GitRelease object from get_latest_release() or get_releases()
            asset_pattern: Regex pattern to match asset name

        Returns:
            Browser download URL, or None if no match found
        """
        try:
            assets = release.get_assets()
            for asset in assets:
                if re.match(asset_pattern, asset.name):
                    url = asset.browser_download_url
                    log.debug(f"Returning url for asset '{asset_pattern}': '{url}'")
                    return url

            log.warning(f"No assets matching '{asset_pattern}' found in release")
            return None
        except Exception as e:
            log.warning(f"Couldn't get asset url for '{asset_pattern}': {e}")
            return None
