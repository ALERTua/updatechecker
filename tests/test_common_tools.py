"""
Tests for the common_tools module, specifically file_needs_update function.
"""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from updatechecker.common_tools import (
    file_needs_update,
    is_filename_archive,
    process_running,
)
from updatechecker.downloader import GitHubDownloader


class TestFileNeedsUpdate:
    """Test file_needs_update function with Content-Length check feature."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file with known size."""
        file_path = temp_dir / "test_file.zip"
        # Create a file with 1000 bytes
        file_path.write_bytes(b"x" * 1000)
        return file_path

    def test_no_metadata_uses_content_length_check_enabled(self, test_file, temp_dir):
        """Test Content-Length check when metadata is missing and check is enabled."""
        # Ensure no metadata file exists
        metadata_path = test_file.with_suffix(test_file.suffix + ".meta.json")
        assert not metadata_path.exists()

        # Mock get_url_headers to return matching Content-Length
        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            mock_headers.return_value = {"content_length": 1000}

            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=True,
            )

            assert result is False  # Should return False - no update needed
            # Check that metadata was saved
            assert metadata_path.exists()

    def test_no_metadata_content_length_differs(self, test_file, temp_dir):
        """Test when Content-Length differs from local file size."""
        metadata_path = test_file.with_suffix(test_file.suffix + ".meta.json")
        assert not metadata_path.exists()

        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            # Server has a different file size
            mock_headers.return_value = {"content_length": 2000}

            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=True,
            )

            assert result is True  # Needs update

    def test_no_metadata_head_fails(self, test_file):
        """Test fallback when HEAD request fails."""
        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            mock_headers.return_value = None

            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=True,
            )

            assert result is None  # Fall back to MD5 comparison

    def test_no_metadata_no_content_length_header(self, test_file):
        """Test fallback when server doesn't return Content-Length."""
        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            mock_headers.return_value = {}  # No content_length

            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=True,
            )

            assert result is None  # Fall back to MD5 comparison

    def test_no_metadata_check_disabled(self, test_file):
        """Test old behavior when Content-Length check is disabled."""
        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            # Should not even call get_url_headers
            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=False,
            )

            assert result is True  # Always needs update
            mock_headers.assert_not_called()

    def test_metadata_exists_uses_etag_check(self, test_file, temp_dir):
        """Test that existing metadata still uses ETag/Last-Modified check."""
        # Create metadata file
        metadata_path = test_file.with_suffix(test_file.suffix + ".meta.json")
        metadata = {
            "url": "https://example.com/file.zip",
            "etag": '"abc123"',
            "last_modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            "content_length": 1000,
            "cached_at": "2025-01-01T00:00:00+00:00",
        }
        metadata_path.write_text(json.dumps(metadata))

        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            # ETag matches
            mock_headers.return_value = {
                "etag": '"abc123"',
                "last_modified": "Wed, 01 Jan 2025 00:00:00 GMT",
                "content_length": 1000,
            }

            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
                use_content_length_check=True,
            )

            assert result is False  # No update needed

    def test_default_parameter_is_true(self, test_file):
        """Test that the default value of use_content_length_check is True."""
        with patch("updatechecker.common_tools.get_url_headers") as mock_headers:
            mock_headers.return_value = {"content_length": 1000}

            # Call without specifying the parameter
            result = file_needs_update(
                "https://example.com/file.zip",
                test_file,
            )

            assert result is False  # Should use Content-Length check


class TestGitPackageToReleases:
    """Test GitHubDownloader.get_releases function with PyGithub."""

    @patch('updatechecker.downloader.github.Github')
    def test_rate_limit_returns_none(self, mock_github):
        """Test that rate limit response returns None."""
        # Mock the Github client to raise an exception (simulating rate limit)
        mock_client = MagicMock()
        mock_github.return_value = mock_client
        mock_client.get_repo.side_effect = Exception("API rate limit exceeded")

        gh = GitHubDownloader()
        result = gh.get_releases('owner/repo')

        assert result is None

    @patch('updatechecker.downloader.github.Github')
    def test_repo_not_found_returns_none(self, mock_github):
        """Test that non-existent repo returns None."""
        # Mock the Github client to raise an exception
        mock_client = MagicMock()
        mock_github.return_value = mock_client
        mock_client.get_repo.side_effect = Exception("Not Found")

        gh = GitHubDownloader()
        result = gh.get_releases('owner/repo')

        assert result is None

    @patch('updatechecker.downloader.github.Github')
    def test_normal_releases_returns_list(self, mock_github):
        """Test that normal releases response returns list."""
        # Mock the release objects
        mock_release1 = MagicMock()
        mock_release1.id = 1
        mock_release1.tag_name = 'v1.0.0'
        mock_release1.title = 'Release 1'
        mock_release1.body = 'Release notes'
        mock_release1.draft = False
        mock_release1.prerelease = False
        mock_release1.published_at = '2024-01-01T00:00:00Z'
        mock_release1.html_url = 'https://github.com/owner/repo/releases/tag/v1.0.0'
        mock_release1.get_assets.return_value = []

        mock_release2 = MagicMock()
        mock_release2.id = 2
        mock_release2.tag_name = 'v0.9.0'
        mock_release2.title = 'Release 2'
        mock_release2.body = 'Release notes'
        mock_release2.draft = False
        mock_release2.prerelease = False
        mock_release2.published_at = '2023-12-01T00:00:00Z'
        mock_release2.html_url = 'https://github.com/owner/repo/releases/tag/v0.9.0'
        mock_release2.get_assets.return_value = []

        # Mock the repo
        mock_repo = MagicMock()
        mock_repo.get_releases.return_value = [mock_release1, mock_release2]

        # Mock the Github client
        mock_client = MagicMock()
        mock_github.return_value = mock_client
        mock_client.get_repo.return_value = mock_repo

        gh = GitHubDownloader()
        result = gh.get_releases('owner/repo')

        assert result is not None
        assert len(result) == 2
        assert result[0].tag_name == 'v1.0.0'
        assert result[1].tag_name == 'v0.9.0'


class TestIsFilenameArchive:
    """Test archive detection by extension and zip magic number."""

    def test_archive_extensions(self):
        assert is_filename_archive('file.zip')
        assert is_filename_archive('file.7z')
        assert is_filename_archive('file.rar')

    def test_extension_is_case_insensitive(self):
        assert is_filename_archive('FILE.ZIP')

    def test_extension_substring_is_not_archive(self):
        # '.zip' as a mere substring used to match ('my.zipper.exe')
        assert not is_filename_archive('my.zipper.exe')

    def test_real_zip_without_extension(self, tmp_path):
        zip_path = tmp_path / 'archive.dat'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('a.txt', 'content')
        assert is_filename_archive(zip_path)

    def test_non_archive_file(self, tmp_path):
        plain = tmp_path / 'plain.txt'
        plain.write_text('hello')
        assert not is_filename_archive(plain)

    def test_nonexistent_non_archive_name(self):
        assert not is_filename_archive('does-not-exist.exe')


class TestProcessRunning:
    """Processes vanishing or denying access mid-scan must not crash it."""

    def test_disappearing_process_is_skipped(self):
        good = MagicMock()
        good.name.return_value = 'app.exe'
        gone = MagicMock()
        gone.name.side_effect = psutil.NoSuchProcess(pid=123)

        with patch(
            'updatechecker.common_tools.psutil.process_iter',
            return_value=[gone, good],
        ):
            result = process_running(executable='app.exe')

        assert result == [good]

    def test_access_denied_on_exe_is_skipped(self):
        denied = MagicMock()
        denied.name.return_value = 'app.exe'
        denied.exe.side_effect = psutil.AccessDenied(pid=1)

        with patch(
            'updatechecker.common_tools.psutil.process_iter',
            return_value=[denied],
        ):
            result = process_running(exe_path='C:/x/app.exe')

        assert result == []

    def test_matching_by_exe_path(self):
        proc = MagicMock()
        proc.name.return_value = 'app.exe'
        proc.exe.return_value = 'C:\\x\\app.exe'

        with patch(
            'updatechecker.common_tools.psutil.process_iter',
            return_value=[proc],
        ):
            result = process_running(exe_path='C:/x/app.exe')

        assert result == [proc]
