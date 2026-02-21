import os
import pprint
import shutil
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
import psutil as psutil
from .logger import Log
from . import constants, common_tools as tools
from .config import config, Entry, substitute_variables

log = Log.getLogger(__name__)


def prepare_entry(entry_dict: dict, name: str, variables: dict) -> Entry:
    """Create an Entry with variable substitution in path fields."""
    entry = entry_dict.copy()
    
    # Get entry-specific variables and merge with global variables
    # Entry-specific variables take priority over global variables
    entry_vars = entry.pop('variables', {}) or {}
    # First expand environment variables in entry-specific variables
    from .config import expand_env_variables, substitute_variables
    for key, value in entry_vars.items():
        entry_vars[key] = expand_env_variables(value)
    # Then expand config variable references in entry-specific variables
    # (entry vars can reference global vars)
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


def process_entry(entry):
    log.printer(f"Processing entry '{entry.name}'")
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

    if git_asset is not None:
        log.debug(f"Trying git package for git asset {git_asset}")
        git_package = tools.url_get_git_package(url)
        if git_package is None:
            log.warning("Url is not for a file and not a git package. Cannot proceed")
            return

        releases = tools.git_package_to_releases(git_package)
        release = tools.git_latest_release(releases)
        url = tools.git_release_get_asset_url(release, git_asset)

    url_file = tools.url_to_filename(url)
    if url_file is None:
        log.warning(f"Url '{url}' is not for a file.")
        return

    target = entry.target
    target = Path(target)
    if target.is_dir():
        entry.target = target = target / url_file

    if not target.exists():
        log.debug(f"Target '{target}' doesn't exist. Just downloading url")
        tools.download_file_from_url(url, target)
        process_archive(entry)
        if launch:
            _launch(launch, arguments)
        return

    target_md5 = tools.md5sum(target)
    temp_file = constants.TEMP_FOLDER / url_file

    def del_temp():
        if temp_file.exists():
            temp_file.unlink()

    del_temp()

    if url_md5 is None:
        tools.download_file_from_url(url, temp_file)
        url_md5 = tools.md5sum(temp_file)
    else:
        url_md5 = tools.read_url(url_md5)
        url_md5 = url_md5.split(' ')[0]

    if target_md5 == url_md5:
        log.printer(f"No need to update '{target}'", color=False)
        del_temp()
        return

    log.debug(f"md5 url vs target: '{url_md5}' '{target_md5}'")
    log.printer(f"Updating {target}")

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
        if proc_running is True:
            tools.kill_process(exe_path=kill_if_locked)
            killed = True

    if temp_file.exists():
        log.debug(f"Moving '{temp_file}' to '{target}'")
        shutil.move(str(temp_file), str(target))
        del_temp()
    else:
        tools.download_file_from_url(url, target)

    process_archive(entry)
    if not target.exists() and bak_file.exists():
        bak_file.rename(target)

    if killed is True:
        if relaunch is True and kill_if_locked is not None:
            _cmd = f"{kill_if_locked} {arguments or ''}"
            os.system(kill_if_locked)
    elif launch:
        _launch(launch, arguments)


def process_archive(entry):
    kill_if_locked = entry.kill_if_locked
    unzip_target = entry.unzip_target
    archive_password = entry.archive_password
    target = Path(entry.target)

    if tools.is_filename_archive(target.name) and unzip_target is not None:
        try:
            tools.unzip_file(target, unzip_target, password=archive_password)
        except Exception as e:
            log.warning(f"Couldn't unzip archive to '{unzip_target}': {type(e)} {e}")

            proc_running = tools.process_running(exe_path=kill_if_locked)
            if proc_running is True:
                tools.kill_process(exe_path=kill_if_locked)

            try:
                tools.unzip_file(target, unzip_target, password=archive_password)
            except Exception as e:
                log.warning(f"Couldn't unzip archive to '{unzip_target}' after unlocking: {type(e)} {e}. Breaking")
                return


def main(_async=True, threads=None):
    from .config import _get_variables
    variables = _get_variables()
    config_entries = [prepare_entry(config_entry, config_entry_name, variables)
                      for config_entry_name, config_entry in config.entries.items()]
    if _async:
        threads = threads or psutil.cpu_count() - 1
        with ThreadPoolExecutor(max_workers=threads) as executor:
            executor.map(process_entry, config_entries)
    else:
        for entry in config_entries:
            process_entry(entry)


if __name__ == '__main__':
    log.verbose = True
    _async = os.getenv('update_checker_dbg', None) is None
    log.debug(f"Async: {_async}")
    main(_async=_async)
    pass
