"""
Tests for the parallel downloader module.
"""

import tempfile
from pathlib import Path

import pytest

from updatechecker.constants import DEFAULT_CHUNK_SIZE
from updatechecker.downloader import (
    calculate_chunks,
    check_server_ranges,
    get_file_size,
)


class TestCalculateChunks:
    """Test chunk calculation for parallel downloads."""

    def test_single_chunk_small_file(self):
        """Test that files smaller than chunk size return single chunk."""
        chunks = calculate_chunks(1024)  # 1 KB
        assert len(chunks) == 1
        assert chunks[0] == (0, 1023)

    def test_exact_chunk_size(self):
        """Test file exactly equal to chunk size."""
        chunks = calculate_chunks(DEFAULT_CHUNK_SIZE)
        assert len(chunks) == 1
        assert chunks[0] == (0, DEFAULT_CHUNK_SIZE - 1)

    def test_two_chunks(self):
        """Test file requiring exactly 2 chunks."""
        file_size = DEFAULT_CHUNK_SIZE + 1
        chunks = calculate_chunks(file_size)
        assert len(chunks) == 2
        assert chunks[0] == (0, DEFAULT_CHUNK_SIZE - 1)
        assert chunks[1] == (DEFAULT_CHUNK_SIZE, file_size - 1)

    def test_multiple_chunks(self):
        """Test file requiring multiple chunks."""
        file_size = DEFAULT_CHUNK_SIZE * 3 + 500
        chunks = calculate_chunks(file_size)
        assert len(chunks) == 4
        # First chunk
        assert chunks[0] == (0, DEFAULT_CHUNK_SIZE - 1)
        # Second chunk
        assert chunks[1] == (DEFAULT_CHUNK_SIZE, 2 * DEFAULT_CHUNK_SIZE - 1)
        # Third chunk
        assert chunks[2] == (2 * DEFAULT_CHUNK_SIZE, 3 * DEFAULT_CHUNK_SIZE - 1)
        # Fourth chunk (smaller)
        assert chunks[3] == (3 * DEFAULT_CHUNK_SIZE, file_size - 1)

    def test_empty_file(self):
        """Test empty file returns empty list."""
        chunks = calculate_chunks(0)
        assert chunks == []

    def test_custom_chunk_size(self):
        """Test with custom chunk size."""
        custom_chunk = 10 * 1024 * 1024  # 10 MB
        file_size = 25 * 1024 * 1024  # 25 MB
        chunks = calculate_chunks(file_size, chunk_size=custom_chunk)
        assert len(chunks) == 3
        assert chunks[0] == (0, custom_chunk - 1)
        assert chunks[1] == (custom_chunk, 2 * custom_chunk - 1)
        assert chunks[2] == (2 * custom_chunk, file_size - 1)


class TestServerRangeSupport:
    """Test server Range header support detection."""

    def test_github_supports_ranges(self):
        """Test that GitHub supports Range requests."""
        # Use a small file from GitHub
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        supports = check_server_ranges(url)
        # GitHub should support Range requests
        assert supports is True

    def test_invalid_url(self):
        """Test invalid URL returns False."""
        supports = check_server_ranges("https://example.com/nonexistent-12345.zip")
        # Should handle gracefully
        assert supports is False


class TestFileSizeDetection:
    """Test file size detection via HEAD request."""

    def test_get_file_size_github(self):
        """Test getting file size from GitHub."""
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        size = get_file_size(url)
        assert size is not None
        assert size > 0

    def test_get_file_size_invalid(self):
        """Test getting file size from invalid URL."""
        size = get_file_size("https://example.com/nonexistent-12345.zip")
        assert size is None


class TestAutoChunkDetection:
    """Test auto-detection of chunked download based on file size."""

    def test_auto_chunk_small_file(self, temp_download_dir):
        """Test that small files don't use chunked download."""
        from updatechecker import downloader

        # A small file URL
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        result = downloader.download_file_from_url(url, dest, chunked_download=None)

        # Should succeed without chunking
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

    def test_force_chunked(self, temp_download_dir):
        """Test forcing chunked download."""
        from updatechecker import downloader

        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        # Force chunked even for small file
        result = downloader.download_file_from_url(url, dest, chunked_download=True)

        # Should work even if server doesn't support ranges
        assert result is not None
        assert result.exists()

    def test_disable_chunked(self, temp_download_dir):
        """Test disabling chunked download."""
        from updatechecker import downloader

        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        result = downloader.download_file_from_url(url, dest, chunked_download=False)

        assert result is not None
        assert result.exists()


@pytest.fixture
def temp_download_dir():
    """Create a temporary directory for downloads."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_unzip_dir():
    """Create a temporary directory for extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
