"""Parallel download module using httpx with chunked parallel downloads."""

import threading
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from .logger import log
from . import constants


def calculate_chunks(
    file_size: int, chunk_size: int = constants.DEFAULT_CHUNK_SIZE
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
    url: str,
    start: int,
    end: int,
    chunk_num: int,
    temp_dir: Path,
    progress_callback: Callable = None,
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
    chunk_file = temp_dir / f"chunk_{int(time.time())}_{chunk_num:04d}"
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


def combine_chunks(chunk_files: list[Path], destination: Path) -> Path:
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

    return destination


def check_server_ranges(url: str) -> bool:
    """Check if server supports HTTP Range requests.

    Args:
        url: URL to check

    Returns:
        True if server supports Range header
    """
    try:
        with httpx.stream("HEAD", url, timeout=30.0, follow_redirects=True) as response:
            accept_ranges = response.headers.get("Accept-Ranges", "none")
            return accept_ranges.lower() == "bytes"
    except Exception as e:
        log.debug(f"Failed to check Range support for '{url}': {e}")
        return False


def get_file_size(url: str) -> int | None:
    """Get file size from URL via HEAD request.

    Args:
        url: URL to check

    Returns:
        File size in bytes, or None if not available
    """
    try:
        with httpx.stream("HEAD", url, timeout=30.0, follow_redirects=True) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                return int(content_length)
    except Exception as e:
        log.debug(f"Failed to get file size for '{url}': {e}")
    return None


def download_file_from_url(source, destination, chunked_download: bool | None = None):
    """Download a file from a URL to a destination path with progress bar.

    Args:
        source: URL to download from
        destination: Path to save the file
        chunked_download: Whether to use chunked parallel download.
                         None = auto-detect based on file size (>= 20MB)
                         True = force chunked download
                         False = never use chunked download

    Returns:
        Path to downloaded file, or None on failure
    """

    filename = source.split('/')[-1]

    def progress_callback(filename: str, downloaded: int, total: int):
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
            file_size = get_file_size(source)
            if file_size is not None:
                should_chunk = file_size >= constants.DEFAULT_CHUNK_SIZE
                log.debug(f"File size: {file_size} bytes, chunked: {should_chunk}")
            else:
                # Can't determine size, use single connection
                should_chunk = False

        download_with_httpx(
            source,
            destination,
            chunked=should_chunk,
            progress_callback=progress_callback,
        )

        log.stop_download_progress()
        log.remove_download_task(filename)
    except Exception as e:
        log.error(f"Error downloading '{source}' to '{destination}'\n{type(e)} {e}")
        return None

    return Path(destination)


def download_with_httpx(
    url: str,
    destination: Path,
    chunked: bool = True,
    progress_callback: Callable = None,
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
    file_size = get_file_size(url)

    if file_size is None:
        log.warning(
            f"Could not determine file size for '{url}', using single connection"
        )
        chunked = False

    if not chunked or file_size < chunk_size:
        # Single connection download with httpx
        return _download_single(url, destination, filename, progress_callback)

    # Check if server supports Range requests
    if not check_server_ranges(url):
        log.debug(
            "Server doesn't support Range requests, falling back to single connection"
        )
        return _download_single(url, destination, filename, progress_callback)

    # Parallel chunked download
    return _download_parallel(
        url, destination, file_size, filename, progress_callback, chunk_size
    )


def _download_single(
    url: str,
    destination: Path,
    filename: str,
    progress_callback: Callable = None,
) -> Path:
    """Single connection download with httpx."""
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
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
    url: str,
    destination: Path,
    file_size: int,
    filename: str,
    progress_callback: Callable = None,
    chunk_size: int = constants.DEFAULT_CHUNK_SIZE,
) -> Path:
    """Parallel chunked download with httpx."""
    chunks = calculate_chunks(file_size, chunk_size)
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
                download_chunk,
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
                return _download_single(url, destination, filename, progress_callback)

    # Combine chunks after all downloads complete
    combine_chunks(chunk_files, destination)

    return destination


def url_get_git_package(url: str) -> str | None:
    """Extract GitHub package name from URL and validate it exists.

    :param url: GitHub URL or package name (e.g., 'owner/repo')
    :return: Package name if valid, None otherwise
    """
    if 'github' in url:
        match = re.search(r'(?<=github\.com/)[^/]+/[^/]+', url)
        if not match:
            return None
        url = match.group(0)

    response = httpx.get(f'https://github.com/{url}/tags.atom', timeout=30.0)
    if response.status_code != 200:
        log.warning(f'{url} is not a valid github url/package')
        return None

    return url


def git_package_to_releases(
    package: str, github_token: str | None = None
) -> list | None:
    """Fetch all releases for a GitHub package.

    Args:
        package: GitHub package in 'owner/repo' format
        github_token: Optional GitHub token for authenticated requests

    Returns:
        List of releases from GitHub API, or None if rate limited
    """
    releases_url = f"https://api.github.com/repos/{package}/releases"
    headers = {}
    if github_token:
        headers['Authorization'] = f'token {github_token}'
    response = httpx.get(releases_url, headers=headers, timeout=30.0)

    if response.status_code != 200:
        token_str = ' with token' if github_token else ' without token'
        log.warning(
            f"GitHub API error for package '{package}'{token_str}: HTTP {response.status_code} {response.text}"
        )
        return None

    data = response.json()
    return data


def git_latest_release(releases: list) -> dict | None:
    """Get the latest release from a list of releases."""
    if releases:
        return releases[0]

    return None


def git_release_get_asset_url(release: dict, asset_name: str) -> str | None:
    """Get the download URL for an asset matching the given pattern."""
    assets = release.get('assets')
    if assets is None:
        log.warning(f"Couldn't get asset url for '{asset_name}'")
        return None

    for asset in assets:
        if re.match(asset_name, asset.get('name', '')):
            url = asset.get('browser_download_url')
            log.debug(f"Returning url for asset '{asset_name}': '{url}'")
            return url

    log.warning(f"No assets matching '{asset_name}' found @ '{release.get('url')}'")
    return None


def url_accessible(_url: str) -> bool:
    """Check if a URL is accessible (returns HTTP 200)."""
    try:
        response = httpx.head(_url, timeout=30.0, follow_redirects=True)
        return response.status_code == 200
    except Exception as e:
        log.debug(f"URL '{_url}' not accessible: {e}")
        return False


def url_to_filename(url):
    parse = urlparse(url)
    base = os.path.basename(parse.path)
    suffix = Path(base).suffix
    if suffix == '':
        log.warning(
            f"Cannot get filename from url '{url}'. No dot in base '{parse.path}'"
        )
        return None

    return base


def read_url(url: str) -> str:
    """Read content from a URL and return as stripped string."""
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.text.strip()


def get_url_headers(url: str) -> dict | None:
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
        log.warning(f"HEAD request failed for '{url}': {type(e).__name__} {e}")
        return None
