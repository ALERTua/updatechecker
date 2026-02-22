"""
Tests for the common_tools module, specifically file_needs_update function.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from updatechecker.common_tools import file_needs_update
from updatechecker.downloader import git_package_to_releases


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
    """Test git_package_to_releases function with rate limiting."""

    @patch('updatechecker.downloader.httpx.get')
    def test_rate_limit_returns_none(self, mock_get):
        """Test that rate limit response returns None."""
        # Mock the response with rate limit error - code returns None only for non-200 status
        mock_response = MagicMock()
        mock_response.status_code = 403  # Use non-200 status to trigger None return
        mock_response.json.return_value = {
            'documentation_url': 'https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting',
            'message': "API rate limit exceeded for 195.3.129.109.",
        }
        mock_get.return_value = mock_response

        result = git_package_to_releases('owner/repo')

        assert result is None
        mock_get.assert_called_once()

    @patch('updatechecker.downloader.httpx.get')
    def test_non_200_status_returns_none(self, mock_get):
        """Test that non-200 status code returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {'message': 'Forbidden'}
        mock_get.return_value = mock_response

        result = git_package_to_releases('owner/repo')

        assert result is None

    @patch('updatechecker.downloader.httpx.get')
    def test_normal_releases_returns_list(self, mock_get):
        """Test that normal releases response returns list."""
        # Mock the response with releases data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {'tag_name': 'v1.0.0', 'name': 'Release 1'},
            {'tag_name': 'v0.9.0', 'name': 'Release 2'},
        ]
        mock_get.return_value = mock_response

        result = git_package_to_releases('owner/repo')

        assert result == [
            {'tag_name': 'v1.0.0', 'name': 'Release 1'},
            {'tag_name': 'v0.9.0', 'name': 'Release 2'},
        ]
        mock_get.assert_called_once()
