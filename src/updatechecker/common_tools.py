import hashlib
import os
import re
import urllib.request
import zipfile
from functools import partial
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve

import psutil as psutil
import requests

from . import constants
from .logger import Log

log = Log.getLogger(__name__)


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
        log.printer(f"Killing process {process.pid}")
        process.kill()


def url_get_git_package(url: str) -> str | None:
    """

    :param url:
    :return:
    """
    if 'github' in url:
        url = re.search('(?<=github.com/)[^/]+/[^/]+', url).group(0)
    request = requests.get(f'https://github.com/{url}/tags.atom')
    if request.status_code != 200:
        log.warning(f'{url} is not a valid github url/package')
        return None

    return url


def git_package_to_releases(package):
    releases_url = f"https://api.github.com/repos/{package}/releases"
    output = requests.get(url=releases_url)
    output = output.json()
    return output


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


def unzip_file(source, destination, members=None, password=None):
    with zipfile.ZipFile(str(source), 'r') as _zip:
        log.debug(f"Unzipping '{source}' to '{destination}'")
        _zip.extractall(str(destination), members=members, pwd=password)


def is_filename_archive(filename):
    archive_exts = ('.zip', '.7z', '.rar')
    return any(ext for ext in archive_exts if ext in filename)
