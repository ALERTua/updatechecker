"""
Tests for the parallel downloader module.
"""

import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from updatechecker.config import Entry
from updatechecker.constants import DEFAULT_CHUNK_SIZE
from updatechecker.downloader import DownloaderFactory, GitHubDownloader, HttpDownloader

# Create instance for testing
_http = HttpDownloader()
calculate_chunks = _http.calculate_chunks
check_server_ranges = _http.check_server_ranges
combine_chunks = _http.combine_chunks
get_file_size = _http.get_file_size
_cleanup_chunk_files = _http._cleanup_chunk_files


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
        # A small file URL
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        result = _http.download_file_from_url(url, dest, chunked_download=None)

        # Should succeed without chunking
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

    def test_force_chunked(self, temp_download_dir):
        """Test forcing chunked download."""
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        # Force chunked even for small file
        result = _http.download_file_from_url(url, dest, chunked_download=True)

        # Should work even if server doesn't support ranges
        assert result is not None
        assert result.exists()

    def test_disable_chunked(self, temp_download_dir):
        """Test disabling chunked download."""
        url = "https://raw.githubusercontent.com/olegbl/d2rmm/master/README.md"
        dest = temp_download_dir / "readme.md"

        result = _http.download_file_from_url(url, dest, chunked_download=False)

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


class TestChunkFileCleanup:
    """Test cleanup of temporary chunk files."""

    def test_cleanup_chunk_files_removes_existing_files(self, temp_download_dir):
        """Test that cleanup removes existing chunk files."""
        # Create temporary chunk files
        chunk1 = temp_download_dir / "chunk_0001"
        chunk2 = temp_download_dir / "chunk_0002"
        chunk1.write_bytes(b"chunk1 content")
        chunk2.write_bytes(b"chunk2 content")

        # Verify files exist
        assert chunk1.exists()
        assert chunk2.exists()

        # Clean up
        _cleanup_chunk_files([chunk1, chunk2])

        # Verify files are removed
        assert not chunk1.exists()
        assert not chunk2.exists()

    def test_cleanup_chunk_files_handles_missing_files(self, temp_download_dir):
        """Test that cleanup handles missing files gracefully."""
        # Non-existent files
        chunk1 = temp_download_dir / "nonexistent_chunk_1"
        chunk2 = temp_download_dir / "nonexistent_chunk_2"

        # Should not raise an exception
        _cleanup_chunk_files([chunk1, chunk2])

    def test_cleanup_chunk_files_handles_partial_files(self, temp_download_dir):
        """Test cleanup when some files exist and some don't."""
        # Create only one file
        chunk1 = temp_download_dir / "chunk_0001"
        chunk2 = temp_download_dir / "chunk_0002"
        chunk1.write_bytes(b"chunk1 content")

        # Verify only chunk1 exists
        assert chunk1.exists()
        assert not chunk2.exists()

        # Clean up both - should handle missing file gracefully
        _cleanup_chunk_files([chunk1, chunk2])

        # Verify chunk1 is removed
        assert not chunk1.exists()

    def test_combine_chunks_removes_chunk_files(self, temp_download_dir):
        """Test that combine_chunks removes chunk files after combining."""
        # Create temporary chunk files
        chunk1 = temp_download_dir / "chunk_0001"
        chunk2 = temp_download_dir / "chunk_0002"
        chunk1.write_bytes(b"first half")
        chunk2.write_bytes(b"second half")

        destination = temp_download_dir / "combined_file.txt"

        # Combine chunks
        result = combine_chunks([chunk1, chunk2], destination)

        # Verify destination exists and has correct content
        assert result == destination
        assert destination.exists()
        assert destination.read_bytes() == b"first halfsecond half"

        # Verify chunk files are removed
        assert not chunk1.exists()
        assert not chunk2.exists()


def _serve(handler_class):
    """Start a local threading HTTP server; return (server, base_url)."""
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f'http://127.0.0.1:{server.server_port}'


@pytest.fixture
def no_content_length_server():
    """Server that streams a body without a Content-Length header."""
    body = b'x' * 4096

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'  # close-delimited body, no Content-Length

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server, base_url = _serve(Handler)
    yield f'{base_url}/file.bin', body
    server.shutdown()


@pytest.fixture
def range_ignoring_server():
    """Server that advertises Accept-Ranges but answers 200 with the full body."""
    body = b'y' * 1000

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            # Deliberately ignore any Range header
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server, base_url = _serve(Handler)
    yield f'{base_url}/file.bin', body
    server.shutdown()


class TestNoContentLength:
    """Downloads without Content-Length must stream to disk, not buffer."""

    def test_download_succeeds_without_content_length(
        self, no_content_length_server, temp_download_dir
    ):
        url, body = no_content_length_server
        dest = temp_download_dir / 'file.bin'

        result = _http.download_file_from_url(url, dest)

        assert result is not None
        assert dest.read_bytes() == body


class TestRangeIgnoringServer:
    """A server answering 200 to a Range request must never corrupt the file."""

    def test_download_chunk_rejects_200(self, range_ignoring_server, temp_download_dir):
        url, _body = range_ignoring_server

        with pytest.raises(RuntimeError, match='ignored Range'):
            _http.download_chunk(url, 0, 99, 0, temp_download_dir)

    def test_parallel_download_falls_back_to_single(
        self, range_ignoring_server, temp_download_dir
    ):
        """Chunked download detects the 200s and falls back to a single
        connection; previously it concatenated N full copies of the file."""
        url, body = range_ignoring_server
        dest = temp_download_dir / 'file.bin'

        result = _http._download_with_httpx(url, dest, chunked=True, chunk_size=100)

        assert result == dest
        assert dest.read_bytes() == body


class TestDisplayName:
    """Progress display names must not leak query strings."""

    def test_query_string_stripped(self):
        name = _http._display_name('https://x.com/path/file.zip?token=secret')
        assert name == 'file.zip'

    def test_plain_url(self):
        assert _http._display_name('https://x.com/file.zip') == 'file.zip'

    def test_no_path_falls_back_to_url(self):
        assert _http._display_name('https://x.com') == 'https://x.com'


class TestDownloaderFactory:
    """Test DownloaderFactory for creating appropriate downloaders based on entry type."""

    def test_returns_http_downloader_when_no_git_asset(self):
        """Test that HttpDownloader is returned when entry has no git_asset."""
        entry = Entry(
            name="test-entry", url="https://example.com/file.zip", target="./downloads"
        )
        downloader = DownloaderFactory.create(entry)

        assert isinstance(downloader, HttpDownloader)
        assert not isinstance(downloader, GitHubDownloader)

    def test_returns_github_downloader_when_git_asset_set(self):
        """Test that GitHubDownloader is returned when entry has git_asset."""
        entry = Entry(
            name="test-entry",
            url="https://github.com/owner/repo",
            target="./downloads",
            git_asset=".*\\.zip",
        )
        downloader = DownloaderFactory.create(entry)

        assert isinstance(downloader, GitHubDownloader)
        assert isinstance(downloader, HttpDownloader)

    @patch('updatechecker.downloader.github.Github')
    def test_github_downloader_receives_token(self, mock_github):
        """Test that GitHubDownloader receives the token when provided."""
        entry = Entry(
            name="test-entry",
            url="https://github.com/owner/repo",
            target="./downloads",
            git_asset=".*\\.zip",
        )
        test_token = "test_github_token_123"
        downloader = DownloaderFactory.create(entry, gh_token=test_token)

        # Verify GitHubDownloader was created with token
        assert isinstance(downloader, GitHubDownloader)
        assert downloader._token == test_token

    @patch('updatechecker.downloader.github.Github')
    def test_github_downloader_works_without_token(self, mock_github):
        """Test that GitHubDownloader works without token."""
        entry = Entry(
            name="test-entry",
            url="https://github.com/owner/repo",
            target="./downloads",
            git_asset=".*\\.zip",
        )
        downloader = DownloaderFactory.create(entry)

        # Verify GitHubDownloader was created without token
        assert isinstance(downloader, GitHubDownloader)
        assert downloader._token is None

    def test_http_downloader_with_md5_entry(self):
        """Test that HttpDownloader is returned for regular entries with MD5."""
        entry = Entry(
            name="test-entry",
            url="https://example.com/file.zip",
            target="./downloads",
            md5="abc123",
        )
        downloader = DownloaderFactory.create(entry)

        assert isinstance(downloader, HttpDownloader)
        assert not isinstance(downloader, GitHubDownloader)

    def test_github_downloader_with_all_options(self):
        """Test GitHubDownloader with all entry options set."""
        entry = Entry(
            name="full-entry",
            url="https://github.com/owner/repo",
            target="./downloads",
            git_asset=".*\\.exe",
            md5="def456",
            chunked_download=True,
        )
        downloader = DownloaderFactory.create(entry, gh_token="token123")

        assert isinstance(downloader, GitHubDownloader)
        assert downloader._token == "token123"
