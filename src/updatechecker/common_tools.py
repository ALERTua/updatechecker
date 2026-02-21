import hashlib
import json
import os
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve

import httpx
import psutil as psutil

from . import constants
from .logger import log


def process_running(executeable=None, exe_path=None, cmdline=None):
    """Returns a list of running processes with executeable equals name and/or full path to executeable equals path

    :param executeable: process executeable name
    :type executeable: str
    :param exe_path: full path to process executeable including name
    :type exe_path: str
    :param cmdline: cmdline or a part of it that can be found in the process cmdline
    :type cmdline: str
    :rtype: list
    """
    process_iter = psutil.process_iter()
    output_processes = []
    for process in process_iter:
        append = False
        process_name = process.name()
        if executeable is not None:
            if process_name.lower() == executeable.lower():
                append = True
            else:
                continue

        if exe_path is not None:
            try:
                process_path = process.exe()
            except Exception as e:
                log.exception(e)
                continue

            if Path(process_path) == Path(exe_path):
                append = True
            else:
                continue

        if cmdline is not None:
            try:
                process_cmdline = process.cmdline()
            except Exception as e:
                log.exception(e)
                continue

            # process_cmdline = [str_decode(_cmdln).lower().replace('\\', '/').strip('/') for _cmdln in process_cmdline]
            process_cmdline = [
                _cmdln.lower().replace('\\', '/').strip('/')
                for _cmdln in process_cmdline
            ]
            if cmdline.lower().replace('\\', '/').strip('/') in process_cmdline:
                append = True
            else:
                continue

        if append:
            output_processes.append(process)
    return output_processes


def kill_process(executeable=None, exe_path=None, cmdline=None):
    running_processes = process_running(
        executeable=executeable, exe_path=exe_path, cmdline=cmdline
    )
    for process in running_processes:
        log.warning(f"Killing process {process.pid}")
        process.kill()


def url_get_git_package(url: str) -> str | None:
    """

    :param url:
    :return:
    """
    if 'github' in url:
        url = re.search('(?<=github.com/)[^/]+/[^/]+', url).group(0)
    response = httpx.get(f'https://github.com/{url}/tags.atom', timeout=30.0)
    if response.status_code != 200:
        log.warning(f'{url} is not a valid github url/package')
        return None

    return url


def git_package_to_releases(package):
    releases_url = f"https://api.github.com/repos/{package}/releases"
    response = httpx.get(releases_url, timeout=30.0)
    return response.json()


def git_latest_release(releases):
    return releases[0]


def git_release_get_asset_url(release, asset_name) -> str | None:
    assets = release.get('assets')
    if assets is None:
        log.warning(f"Couldn't get asset url for '{asset_name}'")
        return None

    matching_assets = list(
        filter(lambda f: re.match(asset_name, f.get('name')) is not None, assets)
    )
    if not any(matching_assets):
        log.warning(
            f"There are no assets of name '{asset_name}' @ '{release.get('url')}"
        )
        return None

    asset = matching_assets[0]
    output = asset.get('browser_download_url')
    log.debug(f"Returning url for asset '{asset_name}': '{output}'")
    return output


def url_accessible(_url):
    try:
        urlopen = urllib.request.urlopen(_url)
        getcode = urlopen.getcode()
    except Exception as e:
        log.exception(e)
        getcode = None

    output = getcode == 200
    log.debug(f"url '{_url}' accessible: {output}")
    return output


def md5sum(path):
    if not isinstance(path, Path):
        try:
            Path(path).exists()
            path = Path(path)
        except Exception as e:
            log.exception(e)
            pass

    if not isinstance(path, Path):
        log.debug(f"Getting md5 of an url '{path}'")
        if not url_accessible(path):
            log.warning(f"Cannot get an md5 of the url '{path}': url is not accessible")
            return None

        filename = url_to_filename(path)
        if filename is None:
            log.warning(
                f"Cannot get md5 from url '{path}': couldn't get filename from url"
            )
            return None

        temp_file_path = constants.TEMP_FOLDER / filename
        if temp_file_path.exists():
            temp_file_path.unlink()

        downloaded_file = download_file_from_url(path, temp_file_path)
        if downloaded_file is None or not downloaded_file.exists():
            log.warning(
                f"Couldn't get url '{path}' md5: couldn't download it to file '{downloaded_file}'"
            )
            return None

        path = downloaded_file

    if not path.exists():
        log.warning("Cannot get md5sum: md5 file doesn't exist")
        return None

    log.debug(f"Getting md5 of '{path}'")
    with path.open('rb') as f:
        d = hashlib.md5()
        for buf in iter(partial(f.read, 128), b''):
            d.update(buf)
    output = d.hexdigest()
    return output


def download_file_from_url(source, destination):
    """Download a file from a URL to a destination path with progress bar."""
    filename = source.split('/')[-1]

    def progress_callback(blocknum, bs, size):
        """Progress callback for urlretrieve."""
        if size > 0:
            downloaded = blocknum * bs
            if downloaded > size:
                downloaded = size
            # Update Rich progress bar
            log.update_download_progress(filename, downloaded, size)

    try:
        urlretrieve(source, str(destination), progress_callback)
    except Exception as e:
        log.error(f"Error downloading '{source}' to '{destination}'\n{type(e)} {e}")
        return None

    return Path(destination)


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


def read_url(url):
    fp = urllib.request.urlopen(url)
    mybytes = fp.read()
    output = mybytes.decode("utf8").strip()
    fp.close()
    return output


def unzip_file(source, destination, members=None, password=None, flatten=False):
    """Extract a zip file to the destination.

    Args:
        source: Path to the zip file
        destination: Directory to extract to
        members: Optional list of members to extract
        password: Optional password for encrypted archives
        flatten: If True and zip contains a single top-level directory,
                 extract files directly to destination (skip the redundant folder)
    """
    if flatten:
        # Extract to a temporary location first
        import tempfile
        import shutil as _shutil

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with zipfile.ZipFile(str(source), 'r') as _zip:
                log.debug(f"Flatten extracting '{source}' to temp '{temp_path}'")
                _zip.extractall(str(temp_path), members=members, pwd=password)

            # Find top-level directories and files
            top_level_items = list(temp_path.iterdir())

            # Check if there's exactly one top-level directory
            top_level_dirs = [item for item in top_level_items if item.is_dir()]
            top_level_files = [item for item in top_level_items if item.is_file()]

            if len(top_level_dirs) == 1 and len(top_level_files) == 0:
                # Single directory - flatten it
                source_dir = top_level_dirs[0]
                log.debug(
                    f"Flattening: moving contents of '{source_dir.name}' to '{destination}'"
                )
                for item in source_dir.iterdir():
                    dest_item = Path(destination) / item.name
                    if dest_item.exists():
                        if dest_item.is_dir():
                            _shutil.rmtree(dest_item)
                        else:
                            dest_item.unlink()
                    _shutil.move(str(item), str(dest_item))
                # Remove the now-empty directory
                source_dir.rmdir()
            else:
                # Multiple directories, files at root, or empty - use normal extraction
                if len(top_level_dirs) > 1:
                    log.debug(
                        "Multiple top-level directories found, using normal extraction"
                    )
                elif len(top_level_files) > 0:
                    log.warning(
                        "flatten=True but archive has no redundant folder to remove "
                        "(files already at root). Extracting normally."
                    )
                else:
                    log.debug("Empty archive, using normal extraction")

                # Copy all contents from temp_path to destination
                for item in top_level_items:
                    dest_item = Path(destination) / item.name
                    if dest_item.exists():
                        if dest_item.is_dir():
                            _shutil.rmtree(dest_item)
                        else:
                            dest_item.unlink()
                    if item.is_dir():
                        _shutil.copytree(str(item), str(dest_item))
                    else:
                        _shutil.copy2(str(item), str(dest_item))
    else:
        with zipfile.ZipFile(str(source), 'r') as _zip:
            log.debug(f"Unzipping '{source}' to '{destination}'")
            _zip.extractall(str(destination), members=members, pwd=password)


def is_filename_archive(filename):
    archive_exts = ('.zip', '.7z', '.rar')
    return any(ext for ext in archive_exts if ext in filename)


def get_url_headers(url: str) -> dict | None:
    """Make HTTP HEAD request to get file metadata without downloading.

    Returns a dict with:
    - etag: ETag header value (unique file identifier)
    - last_modified: Last-Modified header value (timestamp)
    - content_length: Content-Length header value (file size in bytes)
    - None if request fails or URL is not accessible
    """
    try:
        request = urllib.request.Request(url, method='HEAD')
        # Add User-Agent to avoid being blocked by some servers
        request.add_header('User-Agent', 'updatechecker/1.0')

        with urllib.request.urlopen(request, timeout=30) as response:
            headers = response.headers

            result = {
                'etag': headers.get('ETag'),
                'last_modified': headers.get('Last-Modified'),
                'content_length': headers.get('Content-Length'),
            }

            # Convert content_length to int if present
            if result['content_length']:
                try:
                    result['content_length'] = int(result['content_length'])
                except (ValueError, TypeError):
                    result['content_length'] = None

            log.debug(
                f"HEAD request for '{url}': etag={result['etag']}, "
                f"last_modified={result['last_modified']}, "
                f"content_length={result['content_length']}"
            )

            return result

    except Exception as e:
        log.warning(f"HEAD request failed for '{url}': {type(e).__name__} {e}")
        return None


def get_metadata_path(target_path: Path | str) -> Path:
    """Get the path to the sidecar metadata file for a target file."""
    target = Path(target_path)
    return target.with_suffix(target.suffix + '.meta.json')


def delete_metadata(target_path: Path | str) -> bool:
    """Delete the sidecar metadata file for a target file.

    Args:
        target_path: Path to the downloaded file

    Returns:
        True if deleted or didn't exist, False on error
    """
    metadata_path = get_metadata_path(target_path)
    if not metadata_path.exists():
        return True

    try:
        metadata_path.unlink()
        log.debug(f"Deleted metadata file '{metadata_path}'")
        return True
    except Exception as e:
        log.warning(
            f"Failed to delete metadata '{metadata_path}': {type(e).__name__} {e}"
        )
        return False


def save_metadata(target_path: Path | str, headers: dict, url: str) -> bool:
    """Save HTTP headers to a sidecar metadata file.

    Args:
        target_path: Path to the downloaded file
        headers: Dict with etag, last_modified, content_length
        url: The URL the file was downloaded from

    Returns:
        True if successful, False otherwise
    """
    metadata_path = get_metadata_path(target_path)
    metadata = {
        'url': url,
        'etag': headers.get('etag'),
        'last_modified': headers.get('last_modified'),
        'content_length': headers.get('content_length'),
        'cached_at': datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        log.debug(f"Saved metadata to '{metadata_path}'")
        return True
    except Exception as e:
        log.warning(
            f"Failed to save metadata to '{metadata_path}': {type(e).__name__} {e}"
        )
        return False


def load_metadata(target_path: Path | str) -> dict | None:
    """Load cached metadata from sidecar file.

    Args:
        target_path: Path to the downloaded file

    Returns:
        Dict with cached headers or None if file doesn't exist
    """
    metadata_path = get_metadata_path(target_path)

    if not metadata_path.exists():
        log.debug(f"No metadata file found at '{metadata_path}'")
        return None

    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # Verify the URL matches (to handle redirects or URL changes)
        return metadata
    except json.JSONDecodeError as e:
        log.warning(f"Corrupted metadata file '{metadata_path}': {e}")
        return None
    except Exception as e:
        log.warning(
            f"Failed to load metadata from '{metadata_path}': {type(e).__name__} {e}"
        )
        return None


def file_needs_update(url: str, target_path: Path | str) -> bool | None:
    """Check if a remote file has changed since last download.

    Uses HTTP HEAD request to get current headers and compares with
    cached metadata. Falls back to None if HEAD fails.

    Args:
        url: URL of the remote file
        target_path: Path to the locally cached file

    Returns:
        True if file needs update, False if unchanged, None if check failed
    """
    target = Path(target_path)

    # If target doesn't exist, definitely needs update
    # Also clean up any stale metadata file
    if not target.exists():
        log.debug(f"Target '{target}' doesn't exist - needs update")
        delete_metadata(target_path)
        return True

    # Load cached metadata
    cached = load_metadata(target_path)
    if cached is None:
        log.debug("No cached metadata - needs update")
        return True

    # Verify URL matches (to handle redirects)
    if cached.get('url') != url:
        log.debug(f"URL changed from '{cached.get('url')}' to '{url}' - needs update")
        return True

    # Get current headers from server
    current = get_url_headers(url)
    if current is None:
        log.debug("HEAD request failed - can't determine if update needed")
        return None  # Can't determine - need to fall back to MD5

    # Compare headers (priority: ETag -> Last-Modified -> Content-Length)

    # 1. Check ETag (most reliable)
    if current.get('etag') and cached.get('etag'):
        # Handle weak ETags (they start with W/)
        current_etag = current['etag']
        cached_etag = cached['etag']

        if current_etag != cached_etag:
            log.debug(
                f"ETag changed: '{cached_etag}' -> '{current_etag}' - needs update"
            )
            return True
        else:
            log.debug(f"ETag unchanged: '{current_etag}' - no update needed")
            return False

    # 2. Check Last-Modified
    if current.get('last_modified') and cached.get('last_modified'):
        if current['last_modified'] != cached['last_modified']:
            log.debug(
                f"Last-Modified changed: '{cached['last_modified']}' -> '{current['last_modified']}' - needs update"
            )
            return True
        else:
            log.debug(
                f"Last-Modified unchanged: '{current['last_modified']}' - no update needed"
            )
            return False

    # 3. Check Content-Length (file size)
    if current.get('content_length') and cached.get('content_length'):
        if current['content_length'] != cached['content_length']:
            log.debug(
                f"Content-Length changed: {cached['content_length']} -> {current['content_length']} - needs update"
            )
            return True
        else:
            log.debug(
                f"Content-Length unchanged: {current['content_length']} - no update needed"
            )
            return False

    # No headers available to compare
    log.debug("No comparable headers found - can't determine if update needed")
    return None


def update_file_metadata(url: str, target_path: Path | str) -> bool:
    """Update the cached metadata for a file after successful download.

    Args:
        url: URL the file was downloaded from
        target_path: Path to the downloaded file

    Returns:
        True if successful, False otherwise
    """
    headers = get_url_headers(url)
    if headers is None:
        log.warning(f"Could not get headers to save metadata for '{target_path}'")
        return False

    return save_metadata(target_path, headers, url)
