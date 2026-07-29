"""HTTP downloader implementation using httpx for generic URL downloads."""

import os
import shutil
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .. import constants
from ..logger import download_progress, log


class _ChunkCancelled(Exception):
    """Internal: chunk download aborted because a sibling chunk failed."""


class HttpDownloader:
    """HTTP downloader using httpx for generic URL downloads.

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
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Download a specific byte range from URL.

        Args:
            url: URL to download from
            start: Start byte (inclusive)
            end: End byte (inclusive)
            chunk_num: Chunk number for filename
            temp_dir: Temporary directory for chunk files
            progress_callback: Optional callback(completed, total) for progress
            cancel_event: When set, the chunk aborts with _ChunkCancelled
                (a sibling chunk failed and the download is falling back)

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
                # A server that ignores Range returns 200 with the FULL file;
                # combining such "chunks" would produce a corrupt result.
                if response.status_code != 206:
                    raise RuntimeError(
                        f"Server ignored Range request (HTTP {response.status_code})"
                    )

                downloaded = 0
                with open(chunk_file, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        if cancel_event is not None and cancel_event.is_set():
                            raise _ChunkCancelled(chunk_num)
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, chunk_size)

            if downloaded != chunk_size:
                raise RuntimeError(
                    f"Chunk size mismatch: got {downloaded} bytes, expected {chunk_size}"
                )
        except _ChunkCancelled:
            raise
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
            except OSError as e:
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
        except (httpx.HTTPError, httpx.InvalidURL) as e:
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
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:
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
        # Progress rows are keyed by destination: two downloads may share a
        # display name but never a target path
        task_key = str(destination)
        # A caller-supplied callback owns progress reporting; only manage
        # the shared display when using our internal one
        manage_display = progress_callback is None

        def _progress_callback(filename: str, downloaded: int, total: int):
            """Progress callback for download."""
            download_progress.update(task_key, downloaded, total if total > 0 else None)

        if manage_display:
            download_progress.begin(task_key, self._display_name(source))

        success = False
        try:
            # Determine chunked setting based on file size if not specified
            should_chunk = chunked_download
            file_size = None
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
                file_size=file_size,
                task_key=task_key if manage_display else None,
            )
            success = True
        # Deliberate broad catch: this is the resilience boundary of the
        # downloader — callers rely on None for ANY failure kind.
        except Exception as e:  # noqa: BLE001
            log.error(f"Error downloading '{source}' to '{destination}'\n{type(e)} {e}")
            return None
        finally:
            if manage_display:
                download_progress.finish(task_key, success=success)

        return Path(destination)

    @staticmethod
    def _display_name(url: str) -> str:
        """Filename part of a URL for display (query string stripped)."""
        return os.path.basename(urlparse(url).path) or url

    def _download_with_httpx(
        self,
        url: str,
        destination: Path,
        chunked: bool = True,
        progress_callback: Callable | None = None,
        chunk_size: int = constants.DEFAULT_CHUNK_SIZE,
        file_size: int | None = None,
        task_key: str | None = None,
    ) -> Path:
        """Download file using httpx with optional chunked parallel download.

        Args:
            url: URL to download
            destination: Destination file path
            chunked: Whether to use chunked parallel download
            progress_callback: Optional callback(filename, downloaded, total) for progress
            chunk_size: Size of each chunk in bytes
            file_size: Known file size in bytes; fetched via HEAD when None
            task_key: Progress row key, used to reset the row when a chunked
                download falls back to a single connection

        Returns:
            Path to downloaded file
        """
        filename = self._display_name(url)

        if file_size is None:
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
            url,
            destination,
            file_size,
            filename,
            progress_callback,
            chunk_size,
            task_key=task_key,
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

            # Total size from headers; 0 when the server sends no
            # Content-Length - stream to disk either way instead of
            # buffering the whole body in memory
            total = int(response.headers.get("Content-Length", 0))

            downloaded = 0
            with open(destination, 'wb') as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(filename, downloaded, total)

            if total == 0 and progress_callback:
                # Size was unknown; report completion now that it's known
                progress_callback(filename, downloaded, downloaded)

        return destination

    def _download_parallel(
        self,
        url: str,
        destination: Path,
        file_size: int,
        filename: str,
        progress_callback: Callable | None = None,
        chunk_size: int = constants.DEFAULT_CHUNK_SIZE,
        task_key: str | None = None,
    ) -> Path:
        """Parallel chunked download with httpx."""
        chunks = self.calculate_chunks(file_size, chunk_size)
        num_chunks = len(chunks)

        log.debug(f"Downloading {filename} in {num_chunks} parallel chunks")

        # Per-download chunk dir: two concurrent downloads previously shared
        # chunk_NNNN paths in TEMP_FOLDER and overwrote each other's bytes,
        # producing corrupt archives with interleaved content.
        chunk_dir = constants.TEMP_FOLDER / f"{destination.name}.{uuid.uuid4().hex[:8]}"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Track total progress across all chunks with thread-safe locking
        completed_chunks = [0] * num_chunks
        progress_lock = threading.Lock()
        # Set on first failure so the sibling chunk threads abort instead of
        # keeping downloading and racing the single-connection fallback for
        # the same progress row
        cancel_event = threading.Event()

        try:
            with ThreadPoolExecutor(max_workers=num_chunks) as executor:
                # Submit all chunk download tasks in parallel
                futures = []
                for i, (start, end) in enumerate(chunks):
                    # Create callback for this chunk
                    def make_callback(idx, lock):
                        def callback(downloaded, total):
                            # Capture the sum under the lock: reading it
                            # afterwards can deliver a stale (smaller) value
                            # and make the bar wiggle backwards
                            with lock:
                                completed_chunks[idx] = downloaded
                                current_total = sum(completed_chunks)
                            if progress_callback:
                                progress_callback(filename, current_total, file_size)

                        return callback

                    future = executor.submit(
                        self.download_chunk,
                        url,
                        start,
                        end,
                        i,
                        chunk_dir,
                        make_callback(i, progress_lock),
                        cancel_event,
                    )
                    futures.append((i, future))

                # Collect all results after all downloads are submitted
                chunk_files = []
                failed = False
                for chunk_idx, future in futures:
                    try:
                        chunk_files.append(future.result())
                    except _ChunkCancelled:
                        pass
                    except (httpx.HTTPError, RuntimeError, OSError) as e:
                        log.error(f"Chunk {chunk_idx} failed: {e}")
                        failed = True
                        cancel_event.set()
                # Leaving the with-block waits for the remaining chunk
                # threads; they abort promptly via cancel_event

            if failed:
                # Fall back to single connection
                log.warning("Falling back to single connection download")
                if task_key is not None:
                    # Restart the progress row (clock and speed included)
                    # instead of leaving it at the chunks' partial total
                    download_progress.reset(task_key, total=file_size)
                return self._download_single(
                    url, destination, filename, progress_callback
                )

            # Combine chunks after all downloads complete
            self.combine_chunks(chunk_files, destination)
        finally:
            shutil.rmtree(chunk_dir, ignore_errors=True)

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
        except (httpx.HTTPError, httpx.InvalidURL) as e:
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
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            log.debug(f"Failed to get headers for '{url}': {e}")
            return None
