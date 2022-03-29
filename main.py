import hashlib
import json
import locale
import os
import pprint
import re
import shutil
import sys
import urllib.request
import zipfile
from concurrent.futures.thread import ThreadPoolExecutor
from functools import partial
from pathlib import Path

# noinspection PyPackageRequirements
import psutil as psutil
import requests
# noinspection PyUnresolvedReferences
from future.moves.urllib.request import urlretrieve, urlparse

import constants
from logger import Log

log = Log.getLogger(__name__)


def str_decode(_str):
    encs = (locale.getpreferredencoding(True), sys.stdin.encoding, 'utf-8', '866')
    output = _str
    for enc in encs:  # can't figure out why this shit doesn't work the way it should!
        try:
            output = _str.decode(enc)
            break
        except:
            continue
    return output


def process_running(executeable=None, exe_path=None, cmdline=None):
    """ Returns a list of running processes with executeable equals name and/or full path to executeable equals path

    :param executeable: process executeable name
    :type executeable: basestring
    :param exe_path: full path to process executeable including name
    :type exe_path: basestring
    :param cmdline: cmdline or a part of it that can be found in the process cmdline
    :type cmdline: basestring
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
            except:
                continue

            if Path(process_path) == Path(exe_path):
                append = True
            else:
                continue

        if cmdline is not None:
            try:
                process_cmdline = process.cmdline()
            except:
                continue
            process_cmdline = [str_decode(_cmdln).lower().replace('\\', '/').strip('/') for _cmdln in process_cmdline]
            if cmdline.lower().replace('\\', '/').strip('/') in process_cmdline:
                append = True
            else:
                continue

        if append is True:
            output_processes.append(process)
    return output_processes


def kill_process(executeable=None, exe_path=None, cmdline=None):
    running_processes = process_running(executeable=executeable, exe_path=exe_path, cmdline=cmdline)
    for process in running_processes:
        log.printer(f"Killing process {process.pid}")
        process.kill()


def url_get_git_package(url: str) -> str:
    """

    :param url:
    :return:
    """
    if 'github' in url:
        url = re.search('(?<=github.com/)[^/]+/[^/]+', url).group(0)
    request = requests.get(f'https://github.com/{url}/tags.atom')
    if request.status_code != 200:
        raise NameError(f'{url} is not a valid github url/package')
    return url


def git_package_to_releases(package):
    releases_url = f"https://api.github.com/repos/{package}/releases"
    output = requests.get(url=releases_url)
    output = output.json()
    return output


def git_latest_release(releases):
    return releases[0]


def git_release_get_asset_url(release, asset_name):
    assets = release.get('assets')
    if assets is None:
        log.warning(f"Couldn't get asset url for '{asset_name}'")
        return

    matching_assets = list(filter(lambda f: re.match(asset_name, f.get('name')) is not None, assets))
    if not any(matching_assets):
        log.warning(f"There are no assets of name '{asset_name}' @ '{release.get('url')}")
        return

    asset = matching_assets[0]
    output = asset.get('browser_download_url')
    log.debug(f"Returning url for asset '{asset_name}': '{output}'")
    return output


def url_accessible(_url):
    getcode = None
    try:
        urlopen = urllib.request.urlopen(_url)
        getcode = urlopen.getcode()
    except:
        pass
    output = getcode == 200
    log.debug(f"url '{_url}' accessible: {output}")
    return output


def md5sum(path):
    if not isinstance(path, Path):
        try:
            Path(path).exists()
            path = Path(path)
        except:
            pass

    if not isinstance(path, Path):
        log.debug(f"Getting md5 of an url '{path}'")
        if not url_accessible(path):
            log.warning(f"Cannot get an md5 of the url '{path}': url is not accessible")
            return None

        filename = url_to_filename(path)
        if filename is None:
            log.warning(f"Cannot get md5 from url '{path}': couldn't get filename from url")
            return None

        temp_file_path = constants.TEMP_FOLDER / filename
        if temp_file_path.exists():
            temp_file_path.unlink()

        downloaded_file = download_file_from_url(path, temp_file_path)
        if downloaded_file is None or not downloaded_file.exists():
            log.warning(f"Couldn't get url '{path}' md5: couldn't download it to file '{downloaded_file}'")
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
    def basic_progress(blocknum, bs, size):
        if blocknum % 10 == 0:
            log.printer('.', end='', color=False)

    log.printer(f"Downloading '{source}' to '{destination}'", end='', color=False)
    try:
        urlretrieve(source, str(destination), basic_progress)
    except Exception as e:
        log.error(f"Error downloading '{source}' to '{destination}'\n{type(e)} {e}")
        return None
    log.printer('Done', color=False)
    return Path(destination)


def url_to_filename(url):
    parse = urlparse(url)
    base = os.path.basename(parse.path)
    suffix = Path(base).suffix
    if suffix == '':
        log.warning(f"Cannot get filename from url '{url}'. No dot in base '{parse.path}'")
        return None
    return base


def load_config(path=None):
    path = path or constants.CONFIG_FILE
    if not Path(path).exists():
        raise Exception(f"Config doesn't exist @ '{path}'. Create it using config.json.example")

    with open(path, 'r') as config_file:
        config_data = json.load(config_file)

    return config_data


def read_url(url):
    fp = urllib.request.urlopen(url)
    mybytes = fp.read()
    output = mybytes.decode("utf8").strip()
    fp.close()
    return output


def unzip_file(source, destination, members=None, password=None):
    with zipfile.ZipFile(str(source), 'r') as _zip:
        log.debug(f"Unzipping '{source}' to '{destination}'")
        _zip.extractall(str(destination), members=members, pwd=password)


def is_filename_archive(filename):
    archive_exts = ('.zip', '.7z', '.rar')
    return any([ext for ext in archive_exts if ext in filename])


def process_entry(entry):
    log.debug(f"Processing entry:\n{pprint.pformat(entry)}")
    url = entry['url']
    url2 = entry.get('url2') or url
    url_md5 = entry.get('md5')
    git_asset = entry.get('git_asset')
    launch = entry.get('launch')
    arguments = entry.get('arguments')
    kill_if_locked = entry.get('kill_if_locked')
    relaunch = entry.get('relaunch', False)

    def _launch(launch_, arguments_=None):
        __cmd = f'start "" {launch_} {arguments_ or ""}'
        log.debug(f"Launching {__cmd}")
        os.system(__cmd)

    if git_asset is not None:
        log.debug(f"Trying git package for git asset {git_asset}")
        git_package = url_get_git_package(url)
        if git_package is None:
            log.warning("Url is not for a file and not a git package. Cannot proceed")
            return

        releases = git_package_to_releases(git_package)
        release = git_latest_release(releases)
        url = git_release_get_asset_url(release, git_asset)

    url_file = url_to_filename(url)
    if url_file is None:
        log.warning(f"Url '{url}' is not for a file.")
        return

    target = entry['target']
    target = Path(target)
    if target.is_dir():
        target = target / url_file
    entry['target'] = target

    if not target.exists():
        log.debug(f"Target '{target}' doesn't exist. Just downloading url")
        download_file_from_url(url, target) or download_file_from_url(url2, target)
        process_archive(entry)
        if launch:
            _launch(launch, arguments)
        return

    target_md5 = md5sum(target)
    temp_file = constants.TEMP_FOLDER / url_file

    def del_temp():
        if temp_file.exists():
            temp_file.unlink()

    del_temp()

    if url_md5 is None:
        download_file_from_url(url, temp_file) or download_file_from_url(url2, temp_file)
        url_md5 = md5sum(temp_file)
    else:
        url_md5 = read_url(url_md5)
        url_md5 = url_md5.split(' ')[0]

    if target_md5 == url_md5:
        log.printer(f"No need to update '{target}'", color=False)
        del_temp()
        return

    log.debug(f"md5 url vs target: '{url_md5}' '{target_md5}'")
    log.printer(f"Updating {target}")

    bak_file = Path(f'{str(target)}.bak')
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

        proc_running = process_running(exe_path=kill_if_locked)
        if proc_running is True:
            kill_process(exe_path=kill_if_locked)
            killed = True

    if temp_file.exists():
        log.debug(f"Moving '{temp_file}' to '{target}'")
        shutil.move(str(temp_file), str(target))
        del_temp()
    else:
        download_file_from_url(url, target) or download_file_from_url(url2, target)

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
    url = entry['url']
    kill_if_locked = entry.get('kill_if_locked')
    unzip_target = entry.get('unzip_target')
    archive_password = entry.get('archive_password')
    target = entry['target']
    target = Path(target)

    if is_filename_archive(target.name) and unzip_target is not None:
        try:
            unzip_file(target, unzip_target, password=archive_password)
        except Exception as e:
            log.warning(f"Couldn't unzip archive to '{unzip_target}': {type(e)} {e}")

            proc_running = process_running(exe_path=kill_if_locked)
            if proc_running is True:
                kill_process(exe_path=kill_if_locked)

            try:
                unzip_file(target, unzip_target, password=archive_password)
            except Exception as e:
                log.warning(f"Couldn't unzip archive to '{unzip_target}' after unlocking: {type(e)} {e}. Breaking")
                return


def main(args=None, _async=True, threads=None):
    _args = args or sys.argv[1:]
    config = None if not len(_args) else _args[0]
    _config = load_config(config)

    if _async:
        _async_args = [c for c in _config.values()]
        threads = threads or psutil.cpu_count() - 1
        with ThreadPoolExecutor(max_workers=threads) as executor:
            executor.map(process_entry, _async_args)
    else:
        for _, entry in _config.items():
            process_entry(entry)


if __name__ == '__main__':
    log.verbose = True
    _async = os.getenv('update_checker_dbg', None) is None
    log.debug(f"Async: {_async}")
    main(_async=_async)
    pass
