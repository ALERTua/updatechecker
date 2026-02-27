import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Iterable

import psutil

from . import constants
from .downloader import HttpDownloader
from .logger import log

# Create a default HTTP downloader instance for utility functions
_http = HttpDownloader()
url_accessible = _http.url_accessible
url_to_filename = _http.url_to_filename
get_url_headers = _http.get_url_headers


def process_running(executable=None, exe_path=None, cmdline=None):
    """Returns a list of running processes matching the given criteria.

    :param executable: process executable name
    :param exe_path: full path to process executable including name
    :param cmdline: cmdline or a part of it that can be found in the process cmdline
    :return: list of matching psutil.Process objects
    """
    output_processes = []
    for process in psutil.process_iter():
        process_name = process.name()

        if executable is not None and process_name.lower() != executable.lower():
            continue

        if exe_path is not None:
            try:
                process_path = process.exe()
            except Exception as e:
                log.exception(e)
                continue
            if Path(process_path) != Path(exe_path):
                continue

        if cmdline is not None:
            try:
                process_cmdline = process.cmdline()
            except Exception as e:
                log.exception(e)
                continue
            normalized_cmdline = [
                _cmdln.lower().replace('\\', '/').strip('/')
                for _cmdln in process_cmdline
            ]
            if cmdline.lower().replace('\\', '/').strip('/') not in normalized_cmdline:
                continue

        output_processes.append(process)
    return output_processes


def kill_process(executable=None, exe_path=None, cmdline=None):
    running_processes = process_running(
        executable=executable, exe_path=exe_path, cmdline=cmdline
    )
    for process in running_processes:
        log.warning(f"Killing process {process.pid}")
        process.kill()


def md5sum(path):
    """Calculate MD5 hash of a file or URL.

    Args:
        path: Path to file or URL string

    Returns:
        MD5 hexdigest string or None on failure
    """
    # Try to convert to Path if it's a string
    if isinstance(path, str):
        try:
            path = Path(path)
        except Exception:
            pass  # Keep as string, treat as URL

    # Handle URL case
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

        downloaded_file = _http.download_file_from_url(path, temp_file_path)
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
    return d.hexdigest()


def _remove_existing_item(path: Path) -> None:
    """Remove existing file or directory at path."""
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def unzip_file(
    source: str | Path,
    destination: str | Path,
    members: Iterable[str] | None = None,
    password: str | bytes | None = None,
    flatten: bool = False,
) -> None:
    """
    Extract a ZIP archive to a destination directory.

    Args:
        source: Path to the ZIP file.
        destination: Target directory for extraction.
        members: Optional iterable of member names to extract.
        password: Optional password (str or bytes) for encrypted archives.
        flatten: If True and the archive contains exactly one top-level folder,
                 extract its contents directly into destination.

    Raises:
        FileNotFoundError: If source does not exist.
        zipfile.BadZipFile: If the file is not a valid ZIP archive.
        RuntimeError: On invalid extraction paths (Zip Slip protection).
    """
    source_path = Path(source)
    destination_path = Path(destination)

    if not source_path.is_file():
        raise FileNotFoundError(f"ZIP file not found: {source_path}")

    destination_path.mkdir(parents=True, exist_ok=True)

    pwd: bytes | None = None
    if password is not None:
        pwd = password.encode() if isinstance(password, str) else password

    with zipfile.ZipFile(source_path, "r") as zf:
        if pwd:
            zf.setpassword(pwd)

        all_members = zf.namelist()
        selected_members = list(members) if members is not None else all_members

        # Determine flatten root (if applicable)
        flatten_root: str | None = None
        if flatten and members is None:
            top_levels = {
                name.split("/", 1)[0]
                for name in all_members
                if name.strip() and not name.startswith("__MACOSX/")
            }

            if len(top_levels) == 1:
                candidate = next(iter(top_levels))
                # Ensure it's actually a directory structure
                if any(name.startswith(f"{candidate}/") for name in all_members):
                    flatten_root = f"{candidate}/"

        for member in selected_members:
            # Skip directory entries explicitly — handled implicitly
            if member.endswith("/"):
                continue

            original_member = member

            if flatten_root and member.startswith(flatten_root):
                member = member[len(flatten_root) :]
                if not member:
                    continue  # root folder entry itself

            target_path = destination_path / member
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Zip Slip protection
            resolved_target = target_path.resolve()
            if not str(resolved_target).startswith(str(destination_path.resolve())):
                raise RuntimeError(f"Unsafe extraction path detected: {member}")

            with zf.open(original_member, "r") as src, target_path.open("wb") as dst:
                dst.write(src.read())


def is_filename_archive(filename):
    archive_exts = ('.zip', '.7z', '.rar')
    return any(ext for ext in archive_exts if ext in filename) or zipfile.is_zipfile(
        str(filename)
    )


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


def file_needs_update(
    url: str, target_path: Path | str, use_content_length_check: bool = True
) -> bool | None:
    """Check if a remote file has changed since last download.

    Uses HTTP HEAD request to get current headers and compares with
    cached metadata. Falls back to None if HEAD fails.

    Args:
        url: URL of the remote file
        target_path: Path to the locally cached file
        use_content_length_check: If True and metadata is missing but file exists,
                                  use Content-Length comparison to avoid re-download

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
        # No cached metadata - check if we should use Content-Length comparison
        if use_content_length_check:
            log.debug("No cached metadata - attempting Content-Length comparison")

            current = get_url_headers(url)

            if current is None:
                log.debug("HEAD request failed - can't determine if update needed")
                return None  # Fall back to MD5 comparison

            content_length = current.get('content_length')
            if content_length is None:
                log.debug(
                    "No Content-Length in headers - can't determine if update needed"
                )
                return None  # Fall back to MD5 comparison

            local_size = target.stat().st_size
            if local_size == content_length:
                log.debug(
                    f"Content-Length matches local file {target_path} size ({content_length} bytes) - no update needed"
                )
                # Save new metadata since we confirmed the file is current
                save_metadata(target_path, current, url)
                return False
            else:
                log.debug(
                    f"Content-Length differs: local={local_size}, remote={content_length} - needs update"
                )
                return True
        else:
            log.debug(
                "No cached metadata - needs update (Content-Length check disabled)"
            )
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
    if (current_l_m := current.get('last_modified')) and (
        cached_l_m := cached.get('last_modified')
    ):
        if current_l_m != cached_l_m:
            log.debug(
                f"Last-Modified changed: '{cached_l_m}' -> '{current_l_m}' - needs update"
            )
            return True
        else:
            log.debug(f"Last-Modified unchanged: '{current_l_m}' - no update needed")
            return False

    # 3. Check Content-Length (file size)
    if (current_cont_len := current.get('content_length')) and (
        cached_cont_len := cached.get('content_length')
    ):
        if current_cont_len != cached_cont_len:
            log.debug(
                f"Content-Length changed: {cached_cont_len} -> {current_cont_len} - needs update"
            )
            return True
        else:
            log.debug(
                f"Content-Length unchanged: {current_cont_len} - no update needed"
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
