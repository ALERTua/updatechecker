import os
import pprint
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

from . import common_tools as tools
from . import constants
from .config import (
    Config,
    Entry,
    config_filename,
    expand_env_variables,
    substitute_variables,
)
from .downloader import DownloaderFactory
from .logger import log


def get_default_config_path() -> Path:
    """Get the default config path: ~/updatechecker.yaml"""
    local_config = constants.ROOT_FOLDER / config_filename
    if local_config.exists():
        return Path(local_config)

    home_dir = os.getenv('USERPROFILE', os.getenv('HOME', '~')).replace('\\', '/')
    return Path(f"{home_dir}/{config_filename}")


def prepare_entry(entry_dict: dict, name: str, variables: dict) -> Entry:
    """Create an Entry with variable substitution in path fields."""
    entry = entry_dict.copy()

    # Get entry-specific variables and merge with global variables
    # Entry-specific variables take priority over global variables
    entry_vars = entry.pop('variables', {}) or {}

    # Expand environment variables in entry-specific variables
    for key, value in entry_vars.items():
        entry_vars[key] = expand_env_variables(value)

    # Expand config variable references in entry-specific variables
    for key, value in entry_vars.items():
        entry_vars[key] = substitute_variables(value, variables)

    # Merge: global variables first, then entry-specific override them
    merged_variables = {**variables, **entry_vars}

    # Path fields that should have variable substitution
    path_fields = ['target', 'unzip_target', 'kill_if_locked', 'launch', 'arguments']

    # Substitute variables in path fields
    for field in path_fields:
        if field in entry and entry[field]:
            entry[field] = substitute_variables(entry[field], merged_variables)

    return Entry(**entry, name=name)


def process_entry(entry, force: bool = False, gh_token: str | None = None):
    """Process a single entry for update checking.

    Args:
        entry: Entry to process
        force: Force re-download, skip HEAD/MD5 checks
        gh_token: GitHub token for API requests
    """
    log.debug(f"Processing entry '{entry.name}'")
    log.debug(f"{pprint.pformat(entry.model_dump())}")
    url = entry.url
    url_md5 = entry.md5
    git_asset = entry.git_asset
    launch = entry.launch
    arguments = entry.arguments
    kill_if_locked = entry.kill_if_locked
    relaunch = entry.relaunch

    def _launch(launch_, arguments_=None):
        __cmd = f'start "" {launch_} {arguments_ or ""}'
        log.debug(f"Launching {__cmd}")
        os.system(__cmd)

    # Create appropriate downloader based on entry type
    downloader = DownloaderFactory.create(entry, gh_token)

    if git_asset is not None:
        log.debug(f"Trying git package for git asset {git_asset}")
        git_package = downloader.validate_package(url)
        if git_package is None:
            log.warning("Url is not for a file and not a git package. Cannot proceed")
            return

        release = downloader.get_latest_release(git_package)
        if release is None:
            log.warning("No releases found for git package. Cannot proceed")
            return

        url = downloader.get_asset_url(release, git_asset)
        if not url:
            log.warning(
                f"No asset found for git asset {git_asset} within release {release} for package {git_package}."
                f" Cannot proceed"
            )
            return

    url_file = downloader.url_to_filename(url)
    if url_file is None:
        log.warning(f"Url '{url}' is not for a file.")
        return

    target = entry.target
    target = Path(target)
    if target.is_dir():
        entry.target = target = target / url_file

    # Check if file needs update - skip if force is True
    if force:
        needs_update = True
        log.info(f"Force mode: will re-download '{target}'")
    else:
        needs_update = tools.file_needs_update(
            url, target, use_content_length_check=entry.use_content_length_check
        )

    if not target.exists():
        log.debug(f"Target '{target}' doesn't exist. Just downloading url")
        downloader.download_file_from_url(
            url, target, chunked_download=entry.chunked_download
        )
        tools.update_file_metadata(url, target)
        process_archive(entry)
        if launch:
            _launch(launch, arguments)
        return

    # If HEAD check determined file doesn't need update, skip download
    if needs_update is False:
        log.debug(f"No need to update '{target}' (HEAD check: file unchanged)")
        return

    target_md5 = tools.md5sum(target)
    temp_file = constants.TEMP_FOLDER / url_file

    def del_temp():
        if temp_file.exists():
            temp_file.unlink()

    del_temp()

    # If HEAD check failed or returned None, fall back to MD5 comparison
    # Skip if force is True
    if force or needs_update is None:
        if force:
            log.debug("Force mode: skipping MD5 comparison, downloading directly")
        else:
            log.debug("HEAD check failed, falling back to MD5 comparison")
        if url_md5 is None:
            downloader.download_file_from_url(url, temp_file)
            url_md5 = tools.md5sum(temp_file)
        else:
            url_md5 = downloader.read_url(url_md5)
            url_md5 = url_md5.split(' ')[0]

        if not force and target_md5 == url_md5:
            log.info(f"No need to update '{target}' (MD5 check)")
            # Update metadata after confirming no update needed
            tools.update_file_metadata(url, target)
            del_temp()
            return

        log.debug(f"md5 url vs target: '{url_md5}' '{target_md5}'")
    else:
        # HEAD check returned True - need to update, but use MD5 if available
        if url_md5 is not None:
            url_md5 = downloader.read_url(url_md5)
            url_md5 = url_md5.split(' ')[0]
            if target_md5 == url_md5:
                log.info(
                    f"No need to update '{target}' (MD5 matches despite HEAD change)"
                )
                tools.update_file_metadata(url, target)
                return

    log.info(f"Updating {target}")

    bak_file = Path(target.with_suffix('.bak'))
    if bak_file.exists():
        log.debug(f"Deleting old backup for '{target}'")
        bak_file.unlink()

    killed = False
    try:
        target.rename(bak_file)
    except Exception as e:
        if kill_if_locked is None:
            log.warning(f"Couldn't back up '{target}': {type(e)} {e}")
            return

        proc_running = tools.process_running(exe_path=kill_if_locked)
        if proc_running:
            tools.kill_process(exe_path=kill_if_locked)
            killed = True

    if temp_file.exists():
        log.debug(f"Moving '{temp_file}' to '{target}'")
        shutil.move(str(temp_file), str(target))
        del_temp()
    else:
        downloader.download_file_from_url(
            url, target, chunked_download=entry.chunked_download
        )

    # Update metadata after successful download
    tools.update_file_metadata(url, target)

    process_archive(entry)
    if not target.exists() and bak_file.exists():
        bak_file.rename(target)

    if killed:
        if relaunch is True and kill_if_locked is not None:
            _launch(kill_if_locked, arguments)
    elif launch:
        _launch(launch, arguments)


def process_archive(entry):
    kill_if_locked = entry.kill_if_locked
    unzip_target = entry.unzip_target
    archive_password = entry.archive_password
    flatten = entry.flatten
    target = Path(entry.target)

    if tools.is_filename_archive(target.name) and unzip_target is not None:
        try:
            tools.unzip_file(
                target, unzip_target, password=archive_password, flatten=flatten
            )
        except Exception as e:
            log.warning(f"Couldn't unzip archive to '{unzip_target}': {type(e)} {e}")

            proc_running = tools.process_running(exe_path=kill_if_locked)
            if proc_running:
                tools.kill_process(exe_path=kill_if_locked)

            try:
                tools.unzip_file(
                    target, unzip_target, password=archive_password, flatten=flatten
                )
            except Exception as e:
                log.warning(
                    f"Couldn't unzip archive to '{unzip_target}' after unlocking: {type(e)} {e}. Breaking"
                )
                return


def updatechecker(
    config_path: str | Path | None = None,
    _async: bool = True,
    threads: int | None = None,
    entries: list[str] | None = None,
    force: bool = False,
    gh_token: str | None = None,
):
    """Main function with CLI parameters.

    Args:
        config_path: Path to the config file. If None, uses default ~/updatechecker.yaml
        _async: Enable parallel processing (default: True)
        threads: Number of threads for parallel processing (default: CPU count - 1)
        entries: List of entry names to check (default: all)
        force: Force re-download, skip HEAD/MD5 checks
        gh_token: GitHub token for API requests (overrides config and env var)
    """
    # Use provided path or default
    if config_path is None:
        config_path = get_default_config_path()

    # Create Config instance
    config = Config(config_path)
    log.debug(f"Config path: {config_path}")

    # Resolve GitHub token: CLI arg > config > env var
    resolved_gh_token = gh_token or config.github_token or os.getenv('GITHUB_TOKEN')
    log.debug(
        f"GH Token resolved: {'provided' if resolved_gh_token else 'not provided'}"
    )

    # Get variables from config
    variables = config.get_variables()

    config_entries = [
        prepare_entry(config_entry, config_entry_name, variables)
        for config_entry_name, config_entry in config.entries.items()
    ]

    # Filter entries if specified
    if entries:
        entry_names_set = set(entries)
        config_entries = [e for e in config_entries if e.name in entry_names_set]
        if not config_entries:
            log.warning(f"No matching entries found for: {entries}")
            return

    if _async:
        threads = threads or psutil.cpu_count() - 1
        with ThreadPoolExecutor(max_workers=threads) as executor:
            # Pass force flag and gh_token to each entry processing
            list(
                executor.map(
                    lambda e: process_entry(e, force, resolved_gh_token), config_entries
                )
            )
    else:
        for entry in config_entries:
            process_entry(entry, force, resolved_gh_token)
