"""HTTP downloader implementation using httpx for generic URL downloads."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from .. import constants
from ..logger import log


class HttpDownloader:
    """HTTP downloader using httpx for generic URL downloads.

    Supports chunked parallel downloads for large files and
    handles all non-GitHub URL downloads.
    """

    def calculate_chunks(

    Supports chunked parallel downloads for large files and
    handles all non-GitHub URL downloads.
    """

    def calculate_chunks(
        self, file_size: int, chunk_size: int = constants.DEFAULT_CHUNK_SIZE
    ) -> list[tuple[int, int]]:
        """Split file size into ranges for parallel download.

        Args:
            file_size: Total file size in bytes
            chunk_size: Size of each chunk in bytes (default: 20 MB)

        Returns:
            List of (start, end) byte ranges
        """
        if file_size <= 0:
            return []

        if file_size <= chunk_size:
            return [(0, file_size - 1)]

        num_chunks = (file_size + chunk_size - 1) // chunk_size
        chunks = []
        for i in range(num_chunks):
            start = i * chunk_size
            end = min(start + chunk_size - 1, file_size - 1)
            chunks.append((start, end))

        return chunks

    def download_chunk(
        self,
        url: str,
        start: int,
        end: int,
        chunk_num: int,
        temp_dir: Path,
        progress_callback: Callable | None = None,
    ) -> Path:
        """Download a specific byte range from URL.

        Args:
            url: URL to download from
            start: Start byte (inclusive)
            end: End byte (inclusive)
            chunk_num: Chunk number for filename
            temp_dir: Temporary directory for chunk files
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            Path to downloaded chunk file
        """
        chunk_file = temp_dir / f"chunk_{chunk_num:04d}"
        headers = {"Range": f"bytes={start}-{end}"}
        chunk_size = end - start + 1

        try:
            with httpx.stream(
                "GET", url, headers=headers, follow_redirects=True, timeout=3000.0
            ) as response:
                response.raise_for_status()

                downloaded = 0
                with open(chunk_file, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, chunk_size)
        except Exception as e:
            log.warning(f"Failed to download chunk {chunk_num} ({start}-{end}): {e}")
            raise

        return chunk_file

    def combine_chunks(self, chunk_files: list[Path], destination: Path) -> Path:
        """Merge downloaded chunks into single file.

        Args:
            chunk_files: List of chunk file paths (will be sorted by filename)
            destination: Final destination path

        Returns:
            Path to combined file
        """
        with open(destination, 'wb') as out:
            for chunk_file in sorted(chunk_files):
                with open(chunk_file, 'rb') as inp:
                    out.write(inp.read())

        # Clean up chunk files after combining
        self._cleanup_chunk_files(chunk_files)

        return destination

    def _cleanup_chunk_files(self, chunk_files: list[Path]) -> None:
        """Clean up chunk files, ignoring any errors.

        Args:
            chunk_files: List of chunk file paths to delete
        """
        for chunk_file in chunk_files:
            try:
                chunk_file.unlink(missing_ok=True)
            except Exception as e:
                log.debug(f"Failed to clean up chunk file {chunk_file}: {e}")

    def check_server_ranges(self, url: str) -> bool:
        """Check if server supports HTTP Range requests.

        Args:
            url: URL to check

        Returns:
            True if server supports Range header
        """
        try:
            with httpx.stream(
                "HEAD", url, timeout=30.0, follow_redirects=True
            ) as response:
                accept_ranges = response.headers.get("Accept-Ranges", "none")
                return accept_ranges.lower() == "bytes"
        except Exception as e:
            log.debug(f"Failed to check Range support for '{url}': {e}")
            return False

    def get_file_size(self, url: str) -> int | None:
        """Get file size from URL via HEAD request.

        Args:
            url: URL to check

        Returns:
            File size in bytes, or None if not available
        """
        try:
            with httpx.stream(
                "HEAD", url, timeout=30.0, follow_redirects=True
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    return int(content_length)
        except Exception as e:
            log.debug(f"Failed to get file size for '{url}': {e}")
        return None

    def download_file_from_url(
        self,
        source: str,
        destination: Path,
        chunked_download: bool | None = None,
        progress_callback: Callable | None = None,
    ) -> Path | None:
        """Download a file from a URL to a destination path with progress bar.

        Args:
            source: URL to download from
            destination: Path to save the file
            chunked_download: Whether to use chunked parallel download.
                             None = auto-detect based on file size (>= 10MB)
                             True = force chunked download
                             False = never use chunked download
            progress_callback: Optional callback for progress updates

        Returns:
            Path to downloaded file, or None on failure
        """
        filename = source.split('/')[-1]

        def _progress_callback(filename: str, downloaded: int, total: int):
            """Progress callback for download."""
            if total > 0:
                log.update_download_progress(filename, downloaded, total)

        try:
            # Start progress display
            log.start_download_progress()
            # Determine chunked setting based on file size if not specified
            should_chunk = chunked_download
            if should_chunk is None:
                # Auto-detect: check file size first
                file_size = self.get_file_size(source)
                if file_size is not None:
                    should_chunk = file_size >= constants.DEFAULT_CHUNK_SIZE
                    log.debug(f"File size: {file_size} bytes, chunked: {should_chunk}")
                else:
                    # Can't determine size, use single connection
                    should_chunk = False

            self._download_with_httpx(
                source,
                destination,
                chunked=should_chunk,
                progress_callback=progress_callback or _progress_callback,
            )

            log.stop_download_progress()
            log.remove_download_task(filename)
        except Exception as e:
            log.error(f"Error downloading '{source}' to '{destination}'\n{type(e)} {e}")
            return None

        return Path(destination)

    def _download_with_httpx(
        self,
        url: str,
        destination: Path,
        chunked: bool = True,
        progress_callback: Callable | None = None,
        chunk_size: int = constants.DEFAULT_CHUNK_SIZE,
    ) -> Path:
        """Download file using httpx with optional chunked parallel download.

        Args:
            url: URL to download
            destination: Destination file path
            chunked: Whether to use chunked parallel download
            progress_callback: Optional callback(filename, downloaded, total) for progress
            chunk_size: Size of each chunk in bytes

        Returns:
            Path to downloaded file
        """
        filename = url.split('/')[-1]

        # Get file size via HEAD request
        file_size = self.get_file_size(url)

        if file_size is None:
            log.warning(
                f"Could not determine file size for '{url}', using single connection"
            )
            chunked = False

        if not chunked or file_size < chunk_size:
            # Single connection download with httpx
            return self._download_single(url, destination, filename, progress_callback)

        # Check if server supports Range requests
        if not self.check_server_ranges(url):
            log.debug(
                "Server doesn't support Range requests, falling back to single connection"
            )
            return self._download_single(url, destination, filename, progress_callback)

        # Parallel chunked download
        return self._download_parallel(
            url, destination, file_size, filename, progress_callback, chunk_size
        )

    def _download_single(
        self,
        url: str,
        destination: Path,
        filename: str,
        progress_callback: Callable | None = None,
    ) -> Path:
        """Single connection download with httpx."""
        with httpx.stream(
            "GET", url, follow_redirects=True, timeout=3000.0
        ) as response:
            response.raise_for_status()

            # Get total size from headers (may differ from Content-Length if compressed)
            total = int(response.headers.get("Content-Length", 0))
            if total == 0:
                # Read all content first to get actual size
                content = b"".join(response.iter_bytes())
                total = len(content)
                with open(destination, 'wb') as f:
                    f.write(content)
                if progress_callback:
                    progress_callback(filename, total, total)
                return destination

            downloaded = 0

            with open(destination, 'wb') as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(filename, downloaded, total)

        return destination

    def _download_parallel(
        self,
        url: str,
        destination: Path,
        file_size: int,
        filename: str,
        progress_callback: Callable | None = None,
        chunk_size: int = constants.DEFAULT_CHUNK_SIZE,
    ) -> Path:
        """Parallel chunked download with httpx."""
        chunks = self.calculate_chunks(file_size, chunk_size)
        num_chunks = len(chunks)

        log.debug(f"Downloading {filename} in {num_chunks} parallel chunks")

        # Track total progress across all chunks with thread-safe locking
        completed_chunks = [0] * num_chunks
        total_downloaded = [0]  # Use list to allow modification in nested function
        progress_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            # Submit all chunk download tasks in parallel
            futures = []
            for i, (start, end) in enumerate(chunks):
                # Create callback for this chunk
                def make_callback(idx, lock):
                    def callback(downloaded, total):
                        with lock:
                            completed_chunks[idx] = downloaded
                            total_downloaded[0] = sum(completed_chunks)
                        if progress_callback:
                            progress_callback(filename, total_downloaded[0], file_size)

                    return callback

                future = executor.submit(
                    self.download_chunk,
                    url,
                    start,
                    end,
                    i,
                    constants.TEMP_FOLDER,
                    make_callback(i, progress_lock),
                )
                futures.append((i, future))

            # Collect all results after all downloads are submitted
            chunk_files = []
            for chunk_idx, future in futures:
                try:
                    chunk_file = future.result()
                    chunk_files.append(chunk_file)
                except Exception as e:
                    log.error(f"Chunk {chunk_idx} failed: {e}")
                    # Fall back to single connection
                    log.warning("Falling back to single connection download")
                    # Clean up already downloaded chunk files before falling back
                    self._cleanup_chunk_files(chunk_files)
                    return self._download_single(
                        url, destination, filename, progress_callback
                    )

        # Combine chunks after all downloads complete
        self.combine_chunks(chunk_files, destination)

        return destination

    def url_accessible(self, url: str) -> bool:
        """Check if a URL is accessible (returns HTTP 200).

        Args:
            url: URL to check

        Returns:
            True if URL is accessible, False otherwise
        """
        try:
            response = httpx.head(url, timeout=30.0, follow_redirects=True)
            return response.status_code == 200
        except Exception as e:
            log.debug(f"URL '{url}' not accessible: {e}")
            return False

    def url_to_filename(self, url: str) -> str | None:
        """Extract filename from URL.

        Args:
            url: URL to extract filename from

        Returns:
            Filename string, or None if cannot be determined
        """
        parse = urlparse(url)
        base = os.path.basename(parse.path)
        suffix = Path(base).suffix
        if suffix == '':
            log.warning(
                f"Cannot get filename from url '{url}'. No dot in base '{parse.path}'"
            )
            return None

        return base

    def read_url(self, url: str) -> str:
        """Read content from a URL and return as stripped string.

        Args:
            url: URL to read

        Returns:
            Content as string

        Raises:
            httpx.HTTPStatusError: If request fails
        """
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.text.strip()

    def get_url_headers(self, url: str) -> dict | None:
        """Make HTTP HEAD request to get file metadata without downloading.

        Returns a dict with:
        - etag: ETag header value (unique file identifier)
        - last_modified: Last-Modified header value (timestamp)
        - content_length: Content-Length header value (file size in bytes)
        - None if request fails or URL is not accessible
        """
        try:
            response = httpx.head(
                url,
                timeout=30.0,
                follow_redirects=True,
                headers={'User-Agent': 'updatechecker/1.0'},
            )
            response.raise_for_status()

            headers = response.headers
            content_length = headers.get('Content-Length')
            if content_length:
                try:
                    content_length = int(content_length)
                except (ValueError, TypeError):
                    content_length = None

            result = {
                'etag': headers.get('ETag'),
                'last_modified': headers.get('Last-Modified'),
                'content_length': content_length,
            }

            log.debug(
                f"HEAD request for '{url}': etag={result['etag']}, "
                f"last_modified={result['last_modified']}, "
                f"content_length={result['content_length']}"
            )

            return result
        except Exception as e:
            log.debug(f"Failed to get headers for '{url}': {e}")
            return None
